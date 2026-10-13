from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, new_id, now


class Material(Base):
    """Teaching material (BE B) and shared document (BE A) in one table."""

    __tablename__ = "materials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(Unicode(255))
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    public_id: Mapped[str] = mapped_column(String(256), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    # Sharing fields merged from BE A documents.
    format: Mapped[str | None] = mapped_column(String(16))
    resource_type: Mapped[str | None] = mapped_column(String(16), default="raw")
    tags: Mapped[list | None] = mapped_column(JSON, default=list)
    shared_with: Mapped[list | None] = mapped_column(JSON, default=list)
    shared_with_all: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    share_token: Mapped[str | None] = mapped_column(String(64), index=True)
    share_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
