from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.core.schemas import ORMModel


class RecordingOut(ORMModel):
    id: str
    meeting_id: str
    cloudinary_url: str
    duration: float
    size_bytes: int
    status: Literal["uploaded", "pending", "processing", "completed", "failed"]
    created_at: datetime


class PlaybackOut(BaseModel):
    url: str
    expires_in: int = 300
