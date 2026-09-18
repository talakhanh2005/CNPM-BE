from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class StatusOut(BaseModel):
    recording_id: str
    status: Literal["uploaded", "pending", "processing", "completed", "failed"]
    job_id: str | None = None
    attempts: int = 0
    error_message: str | None = None
    updated_at: datetime | None = None
