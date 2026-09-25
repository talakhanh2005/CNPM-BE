from fastapi import APIRouter, Query, Request

from app.core.dependencies import DB, Student, Teacher
from app.core.schemas import Envelope, ok
from app.modules.emotions.repository import EmotionRepository
from app.modules.emotions.schema import EmotionLogsOut, FrameIn, FrameOut
from app.modules.emotions.service import process_frame
from app.modules.meetings.service import MeetingService

router = APIRouter(tags=["BE-06 Realtime emotion"])


@router.post("/meetings/{meeting_id}/frames", response_model=Envelope[FrameOut])
async def frame(meeting_id: str, data: FrameIn, request: Request, user: Student):
    """REST fallback for WebSocket FRAME; shares the same rate limit."""
    return ok(await process_frame(request.app.state, meeting_id, user, data))


@router.get("/meetings/{meeting_id}/emotion-logs", response_model=Envelope[EmotionLogsOut])
def logs(
    meeting_id: str,
    user: Teacher,
    db: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    MeetingService(db).require(meeting_id, user, owner=True)
    samples = EmotionRepository(db).logs(meeting_id, offset, limit)
    return ok(
        {
            "offset": offset,
            "limit": limit,
            "items": [
                {column.name: getattr(sample, column.name) for column in sample.__table__.columns}
                for sample in samples
            ],
        }
    )
