from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.integrations.ai_schema import Emotion


class ReportPoint(BaseModel):
    timestamp: float | datetime
    emotion: Emotion | Literal["fail_detection"]
    confidence: float
    student_id: str | None = None
    recording_id: str | None = None
    sample_id: str | None = None
    mock: bool = False
    probabilities: dict[Emotion, float] | None = None
    face_id: str | None = None
    face_detected: bool = True
    frame_id: str | None = None
    failure_reason: str | None = None


class ReportOut(BaseModel):
    distribution: dict[Emotion, float]
    sample_counts: dict[Emotion, int]
    sample_count: int
    timeline: list[ReportPoint]
    timeline_total: int
    offset: int
    limit: int
    summary: str
    source: Literal["batch", "realtime", "none"]
    time_basis: Literal["recording_seconds", "utc", "none"]
    status: str
    recording_statuses: dict[str, int] = {}
    mock: bool = False
