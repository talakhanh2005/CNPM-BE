import base64
import binascii
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.core.errors import AppError
from app.modules.emotions.repository import EmotionRepository
from app.modules.meetings.service import MeetingService


class EmotionService:
    def __init__(self, session_factory, settings):
        self.factory, self.settings = session_factory, settings

    def authorize(self, meeting_id, user):
        with self.factory() as db:
            meeting = MeetingService(db).require(meeting_id, user, active=True)
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

    def save(self, meeting_id, user, timestamp, result):
        with self.factory() as db:
            # Recheck after AI latency so results cannot be stored after meeting end/leave.
            MeetingService(db).require(meeting_id, user, active=True, lock=True)
            sample = EmotionRepository(db).add(
                meeting_id=meeting_id,
                student_id=user.id,
                timestamp=timestamp,
                **result.model_dump(),
            )
            db.commit()
            return sample.id
