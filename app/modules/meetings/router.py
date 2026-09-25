from typing import Literal

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import DB, CurrentUser, Teacher
from app.core.schemas import Envelope, ok
from app.modules.meetings.repository import MeetingRepository
from app.modules.meetings.schema import (
    IceConfigOut,
    JoinCodeIn,
    MeetingHistoryOut,
    MeetingIn,
    MeetingOut,
)
from app.modules.meetings.service import MeetingService
from app.modules.reports.repository import ReportRepository

router = APIRouter(prefix="/meetings", tags=["BE-02 Meetings"])


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
                "mode": meeting.mode,
                "status": meeting.status,
                "student_id": meeting.student_id,
                "created_at": meeting.created_at,
                "ended_at": meeting.ended_at,
                "recording_statuses": statuses,
                "analysis_status": analysis_status,
                "report_url": f"/meetings/{meeting.id}/report",
            }
        )
    return ok({"items": items, "offset": offset, "limit": limit})


@router.get("/{meeting_id}/ice-config", response_model=Envelope[IceConfigOut])
def ice_config(meeting_id: str, request: Request, user: CurrentUser, db: DB):
    MeetingService(db).require(meeting_id, user, active=True)
    servers = request.app.state.settings.ice_servers
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
def create(data: MeetingIn, user: Teacher, db: DB):
    """Create a scheduled or ongoing classroom and enroll its owner."""
    return ok(MeetingService(db).create(user, data), "Meeting created")


@router.post("/join", response_model=Envelope[MeetingOut])
def join_code(data: JoinCodeIn, user: CurrentUser, db: DB):
    """Resolve a room code and join atomically; no public participant directory."""
    return ok(MeetingService(db).join_code(data.code, user))


@router.get("/{meeting_id}", response_model=Envelope[MeetingOut])
def get(meeting_id: str, user: CurrentUser, db: DB):
    """Get meeting and membership states; restricted to members and owner."""
    return ok(MeetingService(db).require(meeting_id, user))


@router.post("/{meeting_id}/join", response_model=Envelope[MeetingOut])
def join(meeting_id: str, user: CurrentUser, db: DB):
    """Idempotently join; keep the same membership record when rejoining."""
    return ok(MeetingService(db).join(meeting_id, user))


@router.post("/{meeting_id}/leave", response_model=Envelope[MeetingOut])
async def leave(meeting_id: str, request: Request, user: CurrentUser, db: DB):
    """Mark membership left and close any active socket; retain the record."""
    meeting = await run_in_threadpool(MeetingService(db).leave, meeting_id, user)
    await request.app.state.manager.close_user(meeting_id, user.id)
    return ok(meeting)


@router.post("/{meeting_id}/start", response_model=Envelope[MeetingOut])
def start(meeting_id: str, user: Teacher, db: DB):
    """Owning teacher starts a scheduled classroom."""
    return ok(MeetingService(db).start(meeting_id, user))


@router.post("/{meeting_id}/end", response_model=Envelope[MeetingOut])
async def end(meeting_id: str, request: Request, user: Teacher, db: DB):
    """End the classroom, mark all memberships left and close room sockets."""
    meeting = await run_in_threadpool(MeetingService(db).end, meeting_id, user)
    await request.app.state.manager.close_room(meeting_id)
    return ok(meeting)
