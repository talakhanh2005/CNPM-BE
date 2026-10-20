from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.core.db import new_id, now


@dataclass(kw_only=True)
class Recording:
    __collection__: ClassVar[str] = "recordings"
    id: str = field(default_factory=new_id)
    meeting_id: str
    student_id: str | None = None
    cloudinary_url: str
    public_id: str
    format: str
    duration: float
    size_bytes: int
    status: str = "uploaded"
    created_at: datetime = field(default_factory=now)
