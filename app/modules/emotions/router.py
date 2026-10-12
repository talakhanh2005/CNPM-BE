from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.core.dependencies import DB, Student, Teacher
from app.core.errors import AppError
from app.core.schemas import Envelope, ok
from app.modules.emotions.analytics import selected_samples
from app.modules.emotions.model import EmotionSample
from app.modules.emotions.schema import EmotionLogsOut, FrameIn, FrameOut
from app.modules.emotions.service import process_frame
from app.modules.meetings.service import MeetingService

router = APIRouter(tags=["BE-06 Realtime emotion"])


class LogPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logged: bool


def require_sample(db, meeting_id, sample_id, user):
    MeetingService(db).require(meeting_id, user, owner=True)
    sample = db.get(EmotionSample, sample_id)
    if sample is None or sample.meeting_id != meeting_id:
        raise AppError(404, "SAMPLE_NOT_FOUND", "Emotion sample not found in meeting")
    return sample


@router.patch(
    "/meetings/{meeting_id}/emotion-logs/{sample_id}", response_model=Envelope[dict[str, bool]]
)
def update_log(meeting_id: str, sample_id: str, data: LogPatch, user: Teacher, db: DB):
    """Change log visibility only; inference values remain immutable."""
    sample = require_sample(db, meeting_id, sample_id, user)
    sample.logged = data.logged
    db.commit()
    return ok({"logged": sample.logged})


@router.delete("/meetings/{meeting_id}/emotion-logs/{sample_id}", response_model=Envelope[None])
def delete_log(meeting_id: str, sample_id: str, user: Teacher, db: DB):
    """Owning teacher deletes an emotion sample, removing it from analytics."""
    sample = require_sample(db, meeting_id, sample_id, user)
    if getattr(db, "is_mongo", False):
        db.collection("emotion_samples").delete_one({"id": sample.id, "meeting_id": meeting_id})
    else:
        db.delete(sample)
    db.commit()
    return ok(None)


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
    student_id: str | None = None,
    start: Annotated[AwareDatetime | None, Query()] = None,
    end: Annotated[AwareDatetime | None, Query()] = None,
):
    MeetingService(db).require(meeting_id, user, owner=True)
    samples, total = selected_samples(
        db, meeting_id, student_id, start, end, logged=True, offset=offset, limit=limit
    )
    return ok(
        {
            "offset": offset,
            "limit": limit,
            "total": total,
            "items": [
                {column.name: getattr(sample, column.name) for column in sample.__table__.columns}
                for sample in samples
            ],
        }
    )
