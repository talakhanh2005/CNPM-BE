from fastapi import APIRouter

from app.core.dependencies import DB, Teacher
from app.core.schemas import Envelope, ok
from app.modules.analysis.schema import StatusOut
from app.modules.analysis.service import AnalysisService

router = APIRouter(tags=["BE-05 Recorded analysis"])


@router.post(
    "/recordings/{recording_id}/analyze", status_code=202, response_model=Envelope[StatusOut]
)
def analyze(recording_id: str, user: Teacher, db: DB):
    """Persist an analysis job. Idempotent while pending/processing/completed; failed jobs may retry."""
    return ok(AnalysisService(db).enqueue(recording_id, user), "Analysis requested")


@router.get("/recordings/{recording_id}/status", response_model=Envelope[StatusOut])
def status(recording_id: str, user: Teacher, db: DB):
    """Poll durable status every two seconds until completed or failed."""
    return ok(AnalysisService(db).status(recording_id, user))
