from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, new_id, now


class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded','pending','processing','completed','failed')",
            name="ck_recording_status",
        ),
        CheckConstraint("duration > 0", name="ck_recording_duration"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    cloudinary_url: Mapped[str] = mapped_column(String(2048))
    public_id: Mapped[str] = mapped_column(String(256), unique=True)
    format: Mapped[str] = mapped_column(String(16))
    duration: Mapped[float] = mapped_column(Float)
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="uploaded", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
