from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, new_id, now


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','processing','completed','failed')", name="ck_job_state"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id"), unique=True)
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    error_message: Mapped[str | None] = mapped_column(Unicode(256))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id"), primary_key=True)
    result: Mapped[dict] = mapped_column(JSON)
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
