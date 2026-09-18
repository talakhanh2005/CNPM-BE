from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, new_id, now


class EmotionSample(Base):
    __tablename__ = "emotion_samples"
    __table_args__ = (Index("ix_emotion_meeting_time", "meeting_id", "timestamp"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    emotion: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    mock: Mapped[bool]
