from typing import Literal

from pydantic import BaseModel

from app.integrations.ai_schema import SegmentEmotion


class SegmentOut(BaseModel):
    start_seconds: float
    end_seconds: float
    emotion: SegmentEmotion
    avg_confidence: float | None
    student_id: str | None = None


class EmotionShare(BaseModel):
    seconds: float
    percent: float


class SummaryOut(BaseModel):
    total_seconds: float
    analyzed_seconds: float
    no_face_seconds: float
    unknown_seconds: float
    coverage: float
    emotions: dict[str, EmotionShare]
    dominant_emotion: str | None


class RangeOut(BaseModel):
    from_seconds: float
    to_seconds: float


class TimelineOut(BaseModel):
    meeting_id: str
    recording_id: str
    analysis_id: str | None
    model_version: str | None
    duration_seconds: float
    data_status: Literal["COMPLETED"]
    segments_source: Literal["ai", "derived"] | None
    range: RangeOut
    segments: list[SegmentOut]
    summary: SummaryOut
