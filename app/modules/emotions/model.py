from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from app.core.document import Document


@dataclass(kw_only=True, eq=False)
class EmotionSample(Document):
    """Realtime emotion log (README realtime_emotion_logs): prediction metadata, never images."""

    __collection__: ClassVar[str] = "emotion_samples"
    id: str | None = None
    meeting_id: str | None = None
    student_id: str | None = None
    timestamp: datetime | None = None
    emotion: str | None = None
    confidence: float | None = None
    mock: bool | None = None
    frame_id: str | None = None
    received_at: datetime | None = None
    probabilities: dict | None = None
    face_id: str | None = None
    face_detected: bool | None = None
    failure_reason: str | None = None
    logged: bool | None = None
    # Contract v1 §7: realtime_emotion_logs.model_version (null for older AI builds).
    model_version: str | None = None
