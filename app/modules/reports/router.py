from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.core.dependencies import DB, Teacher
from app.core.schemas import Envelope, ok
from app.modules.reports.model import ReportSelection
from app.modules.reports.schema import ReportOut
from app.modules.reports.service import ReportService

router = APIRouter(tags=["BE-07 Reports"])


@router.get("/recordings/{recording_id}/analysis", response_model=Envelope[ReportOut])
def analysis(
    recording_id: str,
    user: Teacher,
    db: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
):
    """Get recording analysis; return an empty report with current status when unavailable."""
    return ok(
        ReportService(db).recording(recording_id, user, ReportSelection("batch", offset, limit))
    )


@router.get("/meetings/{meeting_id}/report", response_model=Envelope[ReportOut])
def report(
    meeting_id: str,
    user: Teacher,
    db: DB,
    source: Literal["auto", "batch", "realtime"] = "auto",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
):
    """Weighted sample distribution. Auto prefers completed batch data, otherwise realtime; never merges sources."""
    return ok(ReportService(db).meeting(meeting_id, user, ReportSelection(source, offset, limit)))
