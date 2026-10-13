from datetime import datetime

from sqlalchemy import ForeignKey, String, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, new_id, now


class EmotionLabel(Base):
    """Manual emotion label with optional media; BE A /api/v1/emotions."""

    __tablename__ = "emotion_labels"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(Unicode(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    media_url: Mapped[str | None] = mapped_column(String(2048))
    media_public_id: Mapped[str | None] = mapped_column(String(256))
    media_resource_type: Mapped[str | None] = mapped_column(String(16))
