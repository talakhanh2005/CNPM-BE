from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, new_id, now


class EmotionSegment(Base):
    """Contract v1 §7 emotion_segments: [start, end) seconds from the start of a recording."""

    __tablename__ = "emotion_segments"
    __table_args__ = (Index("ix_segments_recording_start", "recording_id", "start_seconds"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_job_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_jobs.id"))
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id"))
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id"), index=True)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    emotion: Mapped[str] = mapped_column(String(16))
    avg_confidence: Mapped[float | None] = mapped_column(Float)
    student_id: Mapped[str | None] = mapped_column(String(36))
    sample_count: Mapped[int | None] = mapped_column(Integer)
    model_version: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="derived")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
