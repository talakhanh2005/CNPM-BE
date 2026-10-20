from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.core.dependencies import DB, Teacher
from app.core.schemas import Envelope, ok
from app.modules.emotions.analytics import dashboard
from app.modules.emotions.analytics_schema import DashboardOut
from app.modules.meetings.service import MeetingService
from app.modules.reports.model import ReportSelection
from app.modules.reports.schema import ReportOut
from app.modules.reports.service import ReportService

router = APIRouter(tags=["BE-07 Reports"])


@router.get("/meetings/{meeting_id}/dashboard", response_model=Envelope[DashboardOut])
@router.get("/meetings/{meeting_id}/summary", response_model=Envelope[DashboardOut])
def emotion_dashboard(
    meeting_id: str,
    user: Teacher,
    db: DB,
    student_id: Annotated[str | None, Query(max_length=36)] = None,
    start: Annotated[AwareDatetime | None, Query()] = None,
    end: Annotated[AwareDatetime | None, Query()] = None,
    bucket_seconds: Annotated[int, Query(ge=1, le=3600)] = 60,
):
    """BE Tiền: realtime samples only; inclusive UTC filters, sample-weighted distribution and trends."""
    MeetingService(db).require(meeting_id, user, owner=True)
    return ok(dashboard(db, meeting_id, student_id, start, end, bucket_seconds))


@router.get("/recordings/{recording_id}/analysis", response_model=Envelope[ReportOut])
@router.get("/recordings/{recording_id}/report", response_model=Envelope[ReportOut])
def analysis(
    recording_id: str,
    user: Teacher,
    db: DB,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
):
    """One recording's report; an empty report with the current status when unavailable."""
    return ok(
        ReportService(db).recording(recording_id, user, ReportSelection("batch", offset, limit))
    )


@router.get("/meetings/{meeting_id}/report", response_model=Envelope[ReportOut])
def report(
    meeting_id: str,
    user: Teacher,
    db: DB,
    source: Literal["auto", "batch", "realtime"] = "batch",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    student_id: Annotated[str | None, Query(max_length=36)] = None,
):
    """Sum completed recording reports by sample counts (default ``batch``).

    ``realtime``/``auto`` are explicit opt-ins and never merge sources. ``student_id`` keeps
    that student's recordings (batch) or samples (realtime).
    """
    return ok(
        ReportService(db).meeting(
            meeting_id, user, ReportSelection(source, offset, limit, student_id)
        )
    )
