"""BE A media endpoints: signed direct upload and the room-level recording file."""

import re

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import DB, CurrentUser
from app.core.errors import AppError
from app.core.schemas import ok
from app.integrations.media import SIGNED_RESOURCE_TYPES
from app.modules.meetings.repository import MeetingRepository
from app.modules.meetings.service import MeetingService, not_found

router = APIRouter(prefix="/media", tags=["Media (BE A)"])

SIGNED_UPLOAD_ROOT = "openemotion/uploads"
# Letters, digits, "_", "-" and "/" between segments: no "..", "//" or odd characters.
FOLDER_PATTERN = re.compile(r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$")


class SignedUploadIn(BaseModel):
    folder: str | None = None
    # When set, the upload is tied to a meeting and obeys its mode (realtime: 409).
    meeting_id: str | None = None
    resource_type: str | None = None
    max_bytes: object = None
    allowed_formats: object = None


def validation_error(message):
    return AppError(422, "VALIDATION_ERROR", message)


@router.post("/signed-upload")
def signed_upload(request: Request, user: CurrentUser, db: DB, data: SignedUploadIn | None = None):
    """Signed parameters so the browser uploads straight to Cloudinary.

    The real folder is always openemotion/uploads/{user_id}/{folder}; such files are not
    attached to a meeting, so /media/{public_id} does not manage them.
    """
    data = data or SignedUploadIn()
    if data.meeting_id is not None:
        meeting = MeetingRepository(db).get(data.meeting_id)
        if meeting is None or meeting.teacher_id != user.id:
            raise not_found()
        MeetingService.require_recording_mode(meeting)
    storage, settings = request.app.state.storage, request.app.state.settings
    folder = data.folder or "misc"
    if not isinstance(folder, str) or not FOLDER_PATTERN.match(folder.strip("/")):
        raise validation_error("folder chỉ gồm chữ, số, _, - và / giữa các đoạn.")
    resource_type = data.resource_type or "auto"
    if resource_type not in SIGNED_RESOURCE_TYPES:
        raise validation_error("resource_type phải là image, video, raw hoặc auto.")
    limit = settings.cloudinary_max_upload_bytes
    if data.max_bytes is not None and (
        isinstance(data.max_bytes, bool)
        or not isinstance(data.max_bytes, int)
        or not 0 < data.max_bytes <= limit
    ):
        raise validation_error(f"max_bytes phải trong khoảng 1-{limit}.")
    formats = data.allowed_formats
    if formats is not None and (
        not isinstance(formats, list) or not all(isinstance(item, str) for item in formats)
    ):
        raise validation_error("allowed_formats phải là mảng chuỗi.")
    return ok(
        storage.signed_upload(
            folder=f"{SIGNED_UPLOAD_ROOT}/{user.id}/{folder.strip('/')}",
            resource_type=resource_type,
            max_bytes=data.max_bytes,
            allowed_formats=formats,
        )
    )


def can_view(db, meeting, user):
    if meeting.teacher_id == user.id:
        return True
    return user.role != "teacher" and MeetingRepository(db).participant(meeting.id, user.id)


@router.get("/{public_id:path}")
async def media_info(public_id: str, request: Request, user: CurrentUser, db: DB):
    """Cloudinary details of a meeting's recording file (host or participant)."""
    meeting = await run_in_threadpool(MeetingRepository(db).by_recording_public_id, public_id)
    if meeting is None or not await run_in_threadpool(can_view, db, meeting, user):
        raise not_found()
    info = await run_in_threadpool(
        request.app.state.storage.media_info,
        public_id,
        meeting.recording_resource_type or "video",
    )
    return ok(info.to_api())


@router.delete("/{public_id:path}")
async def delete_media(public_id: str, request: Request, user: CurrentUser, db: DB):
    """Owner deletes the recording file; on storage failure the meeting keeps its reference."""
    meeting = await run_in_threadpool(MeetingRepository(db).by_recording_public_id, public_id)
    if meeting is None or user.role != "teacher" or meeting.teacher_id != user.id:
        raise not_found()
    deleted = await run_in_threadpool(
        request.app.state.storage.delete_media,
        public_id,
        meeting.recording_resource_type or "video",
    )

    def clear():
        meeting.recording_url = meeting.recording_public_id = None
        meeting.recording_resource_type = meeting.processing_started_at = None
        meeting.recording_status = "none"
        meeting.failed_reason = None
        db.commit()

    await run_in_threadpool(clear)
    return ok({"public_id": public_id, "deleted": deleted}, "Đã xoá file ghi.")
