from fastapi import APIRouter, Query, Request

from app.core.dependencies import DB, Student, Teacher
from app.core.schemas import Envelope, ok
from app.modules.emotions.repository import EmotionRepository
from app.modules.emotions.schema import EmotionLogsOut, FrameIn, FrameOut
from app.modules.emotions.service import process_frame
from app.modules.meetings.service import MeetingService

router = APIRouter(tags=["BE-06 Realtime emotion"])


@router.post("/meetings/{meeting_id}/emotions/infer", response_model=Envelope[FrameOut])
async def infer(meeting_id: str, data: FrameIn, request: Request, user: Student):
    """Realtime inference (contract v1 §5.1): student, ongoing realtime meeting, frame in RAM only.

    Same service and rate limit as the WebSocket FRAME message. AI failure still returns 200
    with ``fail_detection``/``ai_error``; the next frame is the retry.
    """
    return ok(await process_frame(request.app.state, meeting_id, user, data))


@router.post(
    "/meetings/{meeting_id}/frames",
    response_model=Envelope[FrameOut],
    deprecated=True,
)
async def frame(meeting_id: str, data: FrameIn, request: Request, user: Student):
    """Deprecated alias of POST /meetings/{meeting_id}/emotions/infer (kept until 23/10)."""
    return await infer(meeting_id, data, request, user)


@router.get("/meetings/{meeting_id}/emotion-logs", response_model=Envelope[EmotionLogsOut])
def logs(
    meeting_id: str,
    user: Teacher,
    db: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    student_id: str | None = Query(None, max_length=36),
):
    MeetingService(db).require(meeting_id, user, owner=True)
    samples = EmotionRepository(db).logs(meeting_id, offset, limit, student_id)
    return ok(
        {
            "offset": offset,
            "limit": limit,
            "items": [sample.to_doc() for sample in samples],
        }
    )
