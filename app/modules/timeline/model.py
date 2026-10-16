from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from app.core.document import Document


@dataclass(kw_only=True, eq=False)
class EmotionSegment(Document):
    """Contract v1 §7 emotion_segments: [start, end) seconds from the start of a recording."""

    __collection__: ClassVar[str] = "emotion_segments"
    id: str | None = None
    analysis_job_id: str | None = None
    recording_id: str | None = None
    meeting_id: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    emotion: str | None = None
    avg_confidence: float | None = None
    student_id: str | None = None
    sample_count: int | None = None
    model_version: str | None = None
    # ai | derived
    source: str | None = None
    created_at: datetime | None = None
