import asyncio
import logging

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.core.db import now
from app.core.dependencies import Student
from app.core.errors import AppError
from app.core.schemas import Envelope, ok
from app.modules.emotions.schema import FrameIn, FrameOut
from app.modules.emotions.service import EmotionService

router = APIRouter(tags=["BE-06 Realtime emotion"])


@router.post("/meetings/{meeting_id}/frames", response_model=Envelope[FrameOut])
async def frame(meeting_id: str, data: FrameIn, request: Request, user: Student):
    """Sample a student frame, persist AI output and deliver only to the owning teacher."""
    state = request.app.state
    service = EmotionService(state.session_factory, state.settings)
    teacher_id = await run_in_threadpool(service.authorize, meeting_id, user)
    state.frame_limiter.take((meeting_id, user.id), state.settings.frame_interval_seconds)
    if state.frame_semaphore.locked():
        raise AppError(429, "AI_BUSY", "Realtime AI capacity reached; retry later")
    async with state.frame_semaphore:
        image = await run_in_threadpool(service.decode_frame, data)
        timestamp = now()
        try:
            async with asyncio.timeout(state.settings.frame_timeout_seconds):
                result = await state.ai.analyze_frame(image, data.content_type)
        except Exception as exc:
            logging.getLogger(__name__).warning("Frame AI request failed (%s)", type(exc).__name__)
            raise AppError(502, "AI_UNAVAILABLE", "Realtime AI failed or timed out") from exc
        sample_id = await run_in_threadpool(service.save, meeting_id, user, timestamp, result)
    event = {
        "type": "EMOTION",
        "sample_id": sample_id,
        "meeting_id": meeting_id,
        "student_id": user.id,
        "timestamp": timestamp.isoformat(),
        **result.model_dump(),
    }
    teacher = state.manager.repo.get(meeting_id, teacher_id)
    delivered = bool(teacher and await state.manager.send(teacher, ok(event)))
    return ok({**event, "delivered_to_teacher": delivered})
