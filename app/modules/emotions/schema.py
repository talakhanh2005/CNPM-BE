from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.core.schemas import ORMModel
from app.integrations.ai_schema import FrameResult


class FrameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame_id: str = Field(min_length=1, max_length=64)
    timestamp: AwareDatetime
    frame_base64: str = Field(
        min_length=1,
        max_length=700000,
        description="Raw base64 without data: prefix; JPEG/PNG only",
    )
    content_type: Literal["image/jpeg", "image/png"]


class FrameOut(FrameResult):
    type: Literal["EMOTION"] = "EMOTION"
    sample_id: str
    meeting_id: str
    student_id: str
    timestamp: datetime
    received_at: datetime
    logged: bool
    delivered_to_teacher: bool = Field(
        description="Best-effort socket delivery; SQL record is authoritative"
    )


class EmotionLogOut(ORMModel):
    id: str
    meeting_id: str
    student_id: str
    frame_id: str | None
    timestamp: datetime
    received_at: datetime | None
    emotion: str
    confidence: float
    probabilities: dict[str, float] | None
    face_id: str | None
    face_detected: bool
    failure_reason: str | None
    logged: bool
    mock: bool


class EmotionLogsOut(BaseModel):
    offset: int
    limit: int
    items: list[EmotionLogOut]
