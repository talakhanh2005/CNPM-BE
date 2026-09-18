from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import DB, CurrentUser, Teacher
from app.core.schemas import Envelope, ok
from app.modules.meetings.schema import JoinCodeIn, MeetingIn, MeetingOut
from app.modules.meetings.service import MeetingService

router = APIRouter(prefix="/meetings", tags=["BE-02 Meetings"])


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
