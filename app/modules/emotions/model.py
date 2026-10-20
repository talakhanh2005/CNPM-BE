from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.core.db import new_id, now


@dataclass(kw_only=True)
class EmotionSample:
    __collection__: ClassVar[str] = "emotion_samples"
    id: str = field(default_factory=new_id)
    meeting_id: str
    student_id: str
    timestamp: datetime = field(default_factory=now)
    emotion: str
    confidence: float
    mock: bool
    frame_id: str | None = None
    received_at: datetime | None = None
    probabilities: dict | None = None
    face_id: str | None = None
    face_detected: bool = True
    failure_reason: str | None = None
    logged: bool = True
