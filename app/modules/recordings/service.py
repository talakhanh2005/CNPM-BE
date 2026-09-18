from app.core.db import new_id
from app.core.errors import AppError
from app.modules.meetings.service import MeetingService
from app.modules.recordings.repository import RecordingRepository


class RecordingService:
    def __init__(self, db, storage=None, settings=None):
        self.db, self.repo, self.storage, self.settings = (
            db,
            RecordingRepository(db),
            storage,
            settings,
        )

    def require(self, recording_id, user, lock=False):
        recording = self.repo.get(recording_id, lock)
        if not recording:
            raise AppError(404, "RECORDING_NOT_FOUND", "Recording not found")
        MeetingService(self.db).require(recording.meeting_id, user, owner=True)
        return recording

    def upload(self, meeting_id, user, data, content_type):
        meeting = MeetingService(self.db).require(meeting_id, user, owner=True)
        if meeting.status == "scheduled":
            raise AppError(409, "MEETING_NOT_STARTED", "Cannot record a scheduled meeting")
        if not data:
            raise AppError(422, "EMPTY_VIDEO", "Video body is empty")
        if len(data) > self.settings.max_upload_bytes:
            raise AppError(413, "VIDEO_TOO_LARGE", "Recording exceeds configured size limit")
        # Check container signatures; Cloudinary validates the actual encoded video.
        valid = (
            content_type in {"video/mp4", "video/quicktime"}
            and len(data) >= 12
            and data[4:8] == b"ftyp"
        ) or (content_type == "video/webm" and data.startswith(b"\x1a\x45\xdf\xa3"))
        if not valid:
            raise AppError(415, "UNSUPPORTED_VIDEO", "Expected an MP4, MOV or WebM video body")
        recording_id = new_id()
        public_id = f"face-emotion/{meeting_id}/{recording_id}"
        # Release SQL transaction before the remote upload.
        self.db.commit()
        asset = self.storage.upload(data, public_id)
        try:
            if asset.duration > self.settings.max_recording_seconds:
                raise AppError(413, "VIDEO_TOO_LONG", "Recording exceeds configured duration limit")
            recording = self.repo.add(
                id=recording_id,
                meeting_id=meeting_id,
                cloudinary_url=asset.url,
                public_id=asset.public_id,
                format=asset.format,
                duration=asset.duration,
                size_bytes=asset.size_bytes,
                status="uploaded",
            )
            self.db.commit()
            return recording
        except Exception:
            self.db.rollback()
            self.storage.delete(asset.public_id)
            raise
