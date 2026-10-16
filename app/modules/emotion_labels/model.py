from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from app.core.document import Document


@dataclass(kw_only=True, eq=False)
class EmotionLabel(Document):
    """Manual emotion label with optional media; BE A /api/v1/emotions."""

    __collection__: ClassVar[str] = "emotion_labels"
    id: str | None = None
    user_id: str | None = None
    label: str | None = None
    created_at: datetime | None = None
    media_url: str | None = None
    media_public_id: str | None = None
    media_resource_type: str | None = None
