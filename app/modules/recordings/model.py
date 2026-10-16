from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from app.core.document import Document


@dataclass(kw_only=True, eq=False)
class Recording(Document):
    __collection__: ClassVar[str] = "recordings"
    id: str | None = None
    meeting_id: str | None = None
    cloudinary_url: str | None = None
    public_id: str | None = None
    format: str | None = None
    duration: float | None = None
    size_bytes: int | None = None
    # uploaded | pending | processing | completed | failed
    status: str | None = None
    created_at: datetime | None = None
