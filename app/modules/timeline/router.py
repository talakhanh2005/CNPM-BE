from fastapi import APIRouter, Query

from app.core.dependencies import DB, Teacher
from app.core.schemas import Envelope, ok
from app.modules.timeline.schema import TimelineOut
from app.modules.timeline.service import TimelineService

router = APIRouter(tags=["Emotion timeline (BE-TU-04)"])


@router.get("/meetings/{meeting_id}/emotions/timeline", response_model=Envelope[TimelineOut])
def timeline(
    meeting_id: str,
    user: Teacher,
    db: DB,
    recording_id: str | None = Query(None, max_length=36),
    from_seconds: float | None = Query(None, ge=0),
    to_seconds: float | None = Query(None, gt=0),
    student_id: str | None = Query(None, max_length=36),
):
    """Segments [start, end) in seconds from the start of the video (contract v1 §5.3).

    Owning teacher, after_session meeting, completed analysis only; otherwise 409 with
    ``details[0].data_status``. A range cuts segments to [from_seconds, to_seconds).
    """
    return ok(
        TimelineService(db).timeline(
            meeting_id, user, recording_id, from_seconds, to_seconds, student_id
        )
    )
