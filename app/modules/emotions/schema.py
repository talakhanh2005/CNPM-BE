from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.integrations.ai_schema import EmotionResult


class FrameIn(BaseModel):
    frame_base64: str = Field(
        min_length=1,
        max_length=700000,
        description="Raw base64 without data: prefix; JPEG/PNG only",
    )
    content_type: Literal["image/jpeg", "image/png"]


class FrameOut(EmotionResult):
    type: Literal["EMOTION"] = "EMOTION"
    sample_id: str
    meeting_id: str
    student_id: str
    timestamp: datetime
    delivered_to_teacher: bool = Field(
        description="Best-effort socket delivery; SQL record is authoritative"
    )
