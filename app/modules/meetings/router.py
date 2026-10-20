import logging
from typing import Literal

from fastapi import APIRouter, File, Query, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.db import now
from app.core.dependencies import DB, CurrentUser, Teacher
from app.core.errors import AppError
from app.core.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    paginate,
    parse_date,
    parse_int,
)
from app.core.schemas import Envelope, ok
from app.integrations.media import read_upload, resolve_content_type
from app.modules.meetings.model import DEFAULT_MEETING_NAME
from app.modules.meetings.repository import MeetingRepository
from app.modules.meetings.schema import (
    IceConfigOut,
    JoinCodeIn,
    MeetingHistoryOut,
    MeetingIn,
    MeetingOut,
    MeetingUpdate,
    RecordingMetaIn,
)
from app.modules.meetings.service import MeetingService, meeting_out, not_found
from app.modules.reports.repository import ReportRepository

router = APIRouter(prefix="/meetings", tags=["BE-02 Meetings"])
RECORDING_FOLDER = "openemotion/recordings"
logger = logging.getLogger(__name__)


def service(db, request):
    return MeetingService(db, request.app.state.settings)


@router.get("", response_model=Envelope[MeetingHistoryOut])
def history(
    user: Teacher,
    db: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    mode: Literal["realtime", "after_session"] | None = None,
):
    items = []
    for meeting in MeetingRepository(db).history(user.id, offset, limit, mode):
        statuses = ReportRepository(db).statuses(meeting.id)
        analysis_status = "not_required"
        if meeting.mode == "after_session":
            analysis_status = (
                "awaiting_recording"
                if not statuses
                else "failed"
                if statuses.get("failed")
                else "processing"
                if statuses.get("processing")
                else "pending"
                if statuses.get("pending")
                else "awaiting_analysis"
                if statuses.get("uploaded")
                else "completed"
            )
        items.append(
            {
                "id": meeting.id,
                "code": meeting.code,
                "name": meeting.name or DEFAULT_MEETING_NAME,
                "mode": meeting.mode,
                "status": meeting.status,
                "student_id": meeting.student_id,
                "student_ids": meeting.student_ids,
                "created_at": meeting.created_at,
                "ended_at": meeting.ended_at,
                "participant_count": sum(
                    1 for p in meeting.participants if p.user_id != meeting.teacher_id
                ),
                "recording_statuses": statuses,
                "analysis_status": analysis_status,
                "report_url": f"/meetings/{meeting.id}/report",
            }
        )
    return ok({"items": items, "offset": offset, "limit": limit})


@router.get("/history")
def filtered_history(
    user: CurrentUser,
    db: DB,
    page: str | None = None,
    size: str | None = None,
    q: str | None = None,
    status: Literal["active", "closed", "scheduled", "ongoing", "ended"] | None = None,
    recording_status: Literal["none", "uploaded", "processing", "completed", "failed"]
    | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
):
    """BE A history: teachers see hosted rooms, students see joined rooms.

    Without ``page`` the data is a plain list (old FE contract); with ``page`` it is
    ``{items, pagination}``.
    """
    page_number = parse_int(page, "page", 1, 1, 10**6)
    page_size = parse_int(size, "size", DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
    meetings = MeetingService(db).history(
        user,
        q=q,
        status=status,
        recording_status=recording_status,
        start=parse_date(from_date, "from_date"),
        end=parse_date(to_date, "to_date"),
    )
    if page is None:
        return ok([meeting_out(db, meeting) for meeting in meetings])
    window, pagination = paginate(meetings, page_number, page_size)
    return ok({"items": [meeting_out(db, meeting) for meeting in window], "pagination": pagination})


@router.get("/{meeting_id}/ice-config", response_model=Envelope[IceConfigOut])
def ice_config(meeting_id: str, request: Request, user: CurrentUser, db: DB):
    MeetingService(db).require(meeting_id, user, active=True)
    servers = request.app.state.settings.effective_ice_servers
    urls = [
        url
        for server in servers
        for url in ([server["urls"]] if isinstance(server["urls"], str) else server["urls"])
    ]
    return ok(
        {
            "iceServers": servers,
            "turn_configured": any(url.startswith(("turn:", "turns:")) for url in urls),
        }
    )


@router.post("", status_code=201, response_model=Envelope[MeetingOut])
def create(data: MeetingIn, request: Request, user: Teacher, db: DB):
    """Create a scheduled or ongoing classroom and enroll its owner."""
    return ok(meeting_out(db, service(db, request).create(user, data)), "Meeting created")


@router.post("/join", response_model=Envelope[MeetingOut])
def join_code(data: JoinCodeIn, request: Request, user: CurrentUser, db: DB):
    """Resolve a room code and join atomically; no public participant directory."""
    return ok(meeting_out(db, service(db, request).join_code(data.code, user)))


@router.get("/lookup")
def lookup(
    request: Request,
    user: CurrentUser,
    db: DB,
    code: str = Query(min_length=4, max_length=12, pattern=r"^[A-Za-z0-9]+$"),
):
    """Does this room code lead to a joinable meeting? No join, no side effects.

    404 unknown code, 409 not ongoing, 403 teacher who does not own it. The FE calls this
    before opening the lobby, so a wrong code never reaches the meeting screen.
    """
    return ok(service(db, request).lookup_code(code, user))


@router.get("/{meeting_id}", response_model=Envelope[MeetingOut])
def get(meeting_id: str, user: CurrentUser, db: DB):
    """Get meeting and membership states; reopening after a page exit rejoins (BE A)."""
    return ok(meeting_out(db, MeetingService(db).rejoin_if_disconnected(meeting_id, user)))


@router.put("/{meeting_id}", response_model=Envelope[MeetingOut])
def update(meeting_id: str, data: MeetingUpdate, user: CurrentUser, db: DB):
    """Owning teacher edits name, description and tags; anyone else gets 404."""
    return ok(meeting_out(db, MeetingService(db).update(meeting_id, user, data)), "Meeting updated")


@router.delete("/{meeting_id}")
async def delete(meeting_id: str, request: Request, user: CurrentUser, db: DB):
    """Soft delete: hidden from history, detail and join; anyone but the owner gets 404.

    Open sockets of the room are closed, as in BE Tiền's delete.
    """
    result = await run_in_threadpool(MeetingService(db).soft_delete, meeting_id, user)
    await request.app.state.manager.close_room(meeting_id)
    return ok(result, "Meeting deleted")


@router.post("/{meeting_id}/join", response_model=Envelope[MeetingOut])
def join(meeting_id: str, request: Request, user: CurrentUser, db: DB):
    """Idempotently join; keep the same membership record when rejoining."""
    return ok(meeting_out(db, service(db, request).join(meeting_id, user)))


@router.post("/{meeting_id}/leave", response_model=Envelope[MeetingOut])
async def leave(meeting_id: str, request: Request, user: CurrentUser, db: DB):
    """Mark membership left and close any active socket; retain the record."""
    meeting = await run_in_threadpool(MeetingService(db).leave, meeting_id, user)
    await request.app.state.manager.close_user(meeting_id, user.id)
    return ok(await run_in_threadpool(meeting_out, db, meeting))


@router.post("/{meeting_id}/disconnect")
def disconnect(meeting_id: str, user: CurrentUser, db: DB):
    """Page exit (sendBeacon/keepalive): mark disconnected instead of leaving the room."""
    return ok(MeetingService(db).disconnect(meeting_id, user))


@router.post("/{meeting_id}/start", response_model=Envelope[MeetingOut])
def start(meeting_id: str, user: Teacher, db: DB):
    """Owning teacher starts a scheduled classroom."""
    return ok(meeting_out(db, MeetingService(db).start(meeting_id, user)))


@router.post("/{meeting_id}/end", response_model=Envelope[MeetingOut])
async def end(meeting_id: str, request: Request, user: Teacher, db: DB):
    """End the classroom, mark all memberships left and close room sockets."""
    meeting = await run_in_threadpool(MeetingService(db).end, meeting_id, user)
    await request.app.state.manager.close_room(meeting_id)
    return ok(await run_in_threadpool(meeting_out, db, meeting))


@router.post("/{meeting_id}/recording", response_model=Envelope[MeetingOut])
def recording_metadata(
    meeting_id: str, user: CurrentUser, db: DB, data: RecordingMetaIn | None = None
):
    """BE A: save duration and mark the room as waiting for analysis (5-minute timeout).

    Video analysis by the AI worker uses ``POST /meetings/{id}/recordings`` instead.
    """
    seconds = data.duration_seconds if data else None
    meeting = MeetingService(db).mark_recording_processing(meeting_id, user, seconds)
    return ok(meeting_out(db, meeting), "Recording saved; waiting for analysis")


@router.post("/{meeting_id}/recording-file")
async def recording_file(
    meeting_id: str,
    request: Request,
    user: CurrentUser,
    db: DB,
    file: UploadFile | None = File(default=None),
):
    """BE A: multipart image/video/audio recording attached to the room on Cloudinary."""
    state = request.app.state
    meetings = MeetingService(db)
    meeting = await run_in_threadpool(meetings.repo.get, meeting_id)
    if meeting is None or not await run_in_threadpool(meetings.can_record, meeting, user):
        raise not_found()
    meetings.require_recording_mode(meeting)
    if file is None or not file.filename:
        raise AppError(422, "VALIDATION_ERROR", "Thiếu file ghi (field `file`).")
    content = await read_upload(file, state.settings.cloudinary_max_upload_bytes)
    if state.upload_semaphore.locked():
        raise AppError(429, "UPLOAD_BUSY", "Upload capacity reached; retry later")
    async with state.upload_semaphore:
        info = await run_in_threadpool(
            lambda: state.storage.upload_media(
                content,
                content_type=resolve_content_type(file.content_type, file.filename),
                folder=f"{RECORDING_FOLDER}/{meeting_id}",
            )
        )
    previous, previous_type = meeting.recording_public_id, meeting.recording_resource_type
    if previous and previous != info.public_id:
        try:
            await run_in_threadpool(state.storage.delete_media, previous, previous_type or "video")
        except AppError:
            # Never block a new upload because the old file could not be removed.
            logger.warning("Could not delete previous recording %s", previous)

    def save():
        meeting.recording_url = info.url
        meeting.recording_public_id = info.public_id
        meeting.recording_resource_type = info.resource_type
        meeting.recording_status = "processing"
        meeting.processing_started_at = now()
        meeting.failed_reason = None
        db.commit()

    await run_in_threadpool(save)
    return ok(
        {"recording_url": info.url, "public_id": info.public_id, "media": info.to_api()},
        "Recording uploaded; waiting for analysis",
    )
