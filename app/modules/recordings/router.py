import asyncio

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import DB, Teacher
from app.core.errors import AppError
from app.core.schemas import Envelope, ok
from app.modules.meetings.service import MeetingService
from app.modules.recordings.schema import PlaybackOut, RecordingOut
from app.modules.recordings.service import RecordingService

router = APIRouter(tags=["BE-04 Recordings"])


@router.post(
    "/meetings/{meeting_id}/recordings",
    status_code=201,
    response_model=Envelope[RecordingOut],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                mime: {"schema": {"type": "string", "format": "binary"}}
                for mime in ["video/mp4", "video/webm", "video/quicktime"]
            },
        }
    },
)
async def upload(meeting_id: str, request: Request, user: Teacher, db: DB):
    """Upload a raw video body (not multipart). RAM-only buffering with hard limits."""
    state = request.app.state
    await run_in_threadpool(MeetingService(db).require, meeting_id, user, True)
    await run_in_threadpool(db.commit)
    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in {"video/mp4", "video/webm", "video/quicktime"}:
        raise AppError(415, "UNSUPPORTED_VIDEO", "Use video/mp4, video/webm or video/quicktime")
    length = request.headers.get("content-length")
    if length:
        try:
            size = int(length)
            if size < 0:
                raise ValueError()
        except ValueError as exc:
            raise AppError(400, "INVALID_LENGTH", "Invalid Content-Length") from exc
        if size > state.settings.max_upload_bytes:
            raise AppError(413, "VIDEO_TOO_LARGE", "Recording exceeds configured size limit")
    if state.upload_semaphore.locked():
        raise AppError(429, "UPLOAD_BUSY", "Upload capacity reached; retry later")
    async with state.upload_semaphore:
        data = bytearray()
        try:
            async with asyncio.timeout(state.settings.upload_timeout_seconds):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > state.settings.max_upload_bytes:
                        raise AppError(
                            413, "VIDEO_TOO_LARGE", "Recording exceeds configured size limit"
                        )
                    data.extend(chunk)
        except TimeoutError as exc:
            raise AppError(408, "UPLOAD_TIMEOUT", "Request video stream timed out") from exc
        service = RecordingService(db, state.storage, state.settings)
        recording = await run_in_threadpool(service.upload, meeting_id, user, bytes(data), mime)
        return ok(recording, "Recording uploaded")


@router.get("/recordings/{recording_id}", response_model=Envelope[RecordingOut])
def get_recording(recording_id: str, user: Teacher, db: DB):
    """Get recording metadata, restricted to the meeting's owning teacher."""
    return ok(RecordingService(db).require(recording_id, user))


@router.get("/recordings/{recording_id}/playback", response_model=Envelope[PlaybackOut])
def playback(recording_id: str, request: Request, user: Teacher, db: DB):
    """Generate a signed five-minute download URL for the authenticated asset."""
    recording = RecordingService(db).require(recording_id, user)
    return ok(
        {
            "url": request.app.state.storage.download_url(recording.public_id, recording.format),
            "expires_in": 300,
        }
    )
