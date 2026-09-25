from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, new_id, now


class EmotionSample(Base):
    __tablename__ = "emotion_samples"
    __table_args__ = (
        Index("ix_emotion_meeting_time", "meeting_id", "timestamp"),
        Index("ix_emotion_received", "meeting_id", "student_id", "received_at"),
        Index("ix_emotion_logged", "meeting_id", "student_id", "logged", "received_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    emotion: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    mock: Mapped[bool]
    frame_id: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    probabilities: Mapped[dict | None] = mapped_column(JSON)
    face_id: Mapped[str | None] = mapped_column(String(128))
    face_detected: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    failure_reason: Mapped[str | None] = mapped_column(String(16))
    logged: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
