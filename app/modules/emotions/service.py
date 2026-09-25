import asyncio
import base64
import binascii
import logging
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app.core.concurrency import meeting_lock
from app.core.db import now
from app.core.errors import AppError
from app.core.schemas import ok
from app.integrations.ai_schema import FrameResult
from app.modules.emotions.repository import EmotionRepository
from app.modules.meetings.service import MeetingService


class EmotionService:
    def __init__(self, session_factory, settings):
        self.factory, self.settings = session_factory, settings

    def authorize(self, meeting_id, user):
        if user.role != "student":
            raise AppError(403, "FORBIDDEN", "Only students may submit frames")
        with self.factory() as db:
            meeting = MeetingService(db).require(meeting_id, user, active=True)
            if meeting.mode != "realtime":
                raise AppError(409, "INVALID_MEETING_MODE", "Frames require realtime mode")
            return meeting.teacher_id

    def decode_frame(self, data):
        try:
            frame = base64.b64decode(data.frame_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise AppError(422, "INVALID_FRAME", "Frame is not valid base64") from exc
        if len(frame) > self.settings.max_frame_bytes:
            raise AppError(413, "FRAME_TOO_LARGE", "Frame exceeds configured size limit")
        try:
            with Image.open(BytesIO(frame)) as img:
                if img.format != {"image/jpeg": "JPEG", "image/png": "PNG"}[data.content_type]:
                    raise ValueError("Image type mismatch")
                if img.width * img.height > 1920 * 1080:
                    raise ValueError("Frame exceeds 1920x1080 pixel budget")
                img.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise AppError(
                422, "INVALID_FRAME", "Invalid JPEG/PNG or frame pixel budget exceeded"
            ) from exc
        return frame

    def save(self, meeting_id, user, received_at, result):
        with meeting_lock(meeting_id), self.factory() as db:
            # Recheck after AI latency so results cannot be stored after meeting end/leave.
            MeetingService(db).require(meeting_id, user, active=True, lock=True)
            repo = EmotionRepository(db)
            latest = repo.latest(meeting_id, user.id)
            previous = repo.latest(meeting_id, user.id, logged=True)
            fresh = latest is None or received_at > (latest.received_at or latest.timestamp)
            logged = fresh and (
                previous is None
                or (result.emotion, result.failure_reason)
                != (previous.emotion, previous.failure_reason)
                or (received_at - (previous.received_at or previous.timestamp)).total_seconds()
                >= self.settings.emotion_log_interval_seconds
            )
            sample = repo.add(
                meeting_id=meeting_id,
                student_id=user.id,
                received_at=received_at,
                logged=logged,
                **result.model_dump(),
            )
            db.commit()
            return sample.id, logged


async def process_frame(state, meeting_id, user, data, is_current=None):
    received_at = now()
    service = EmotionService(state.session_factory, state.settings)
    teacher_id = await run_in_threadpool(service.authorize, meeting_id, user)
    state.frame_limiter.take((meeting_id, user.id), state.settings.frame_interval_seconds)
    if state.frame_semaphore.locked():
        raise AppError(429, "AI_BUSY", "Realtime AI capacity reached; retry later")
    async with state.frame_semaphore:
        image = await run_in_threadpool(service.decode_frame, data)
        try:
            async with asyncio.timeout(state.settings.frame_timeout_seconds):
                result = await state.ai.analyze_frame(
                    image, data.content_type, data.frame_id, data.timestamp
                )
                result = FrameResult.model_validate(result)
                if result.frame_id != data.frame_id or result.timestamp != data.timestamp:
                    raise ValueError("AI returned mismatched frame metadata")
        except Exception as exc:
            logging.getLogger(__name__).warning("Frame AI request failed (%s)", type(exc).__name__)
            result = FrameResult.failed(data.frame_id, data.timestamp)
        if is_current and not is_current():
            raise AppError(409, "SOCKET_REPLACED", "Frame belongs to a replaced connection")
        sample_id, logged = await run_in_threadpool(
            service.save, meeting_id, user, received_at, result
        )
    event = {
        "type": "EMOTION",
        "sample_id": sample_id,
        "meeting_id": meeting_id,
        "student_id": user.id,
        "received_at": received_at.isoformat(),
        "logged": logged,
        **result.model_dump(mode="json"),
    }
    teacher = state.manager.repo.get(meeting_id, teacher_id)
    delivered = bool(logged and teacher and await state.manager.send(teacher, ok(event)))
    return {**event, "delivered_to_teacher": delivered}
