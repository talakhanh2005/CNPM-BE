from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Metrics(BaseModel):
    sample_count: int
    total_samples: int
    failed_samples: int
    sample_counts: dict[str, int]
    distribution: dict[str, float]
    average_confidence: float | None
    average_probabilities: dict[str, float]
    positive_ratio: float
    negative_ratio: float
    neutral_ratio: float
    positive_negative_ratio: float | None


class StudentMetrics(Metrics):
    student_id: str


class TrendMetrics(Metrics):
    timestamp: datetime


class DashboardOut(Metrics):
    meeting_id: str
    student_id: str | None
    start: datetime | None
    end: datetime | None
    bucket_seconds: int
    students: list[StudentMetrics]
    trend: list[TrendMetrics]


class AggregateOut(DashboardOut):
    type: Literal["EMOTION_AGGREGATE"] = "EMOTION_AGGREGATE"
    window_seconds: int
