from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.core.db import new_id, now


@dataclass(kw_only=True)
class Material:
    __collection__: ClassVar[str] = "materials"
    id: str = field(default_factory=new_id)
    meeting_id: str
    uploaded_by: str
    filename: str
    content_type: str
    size_bytes: int
    public_id: str
    created_at: datetime = field(default_factory=now)
