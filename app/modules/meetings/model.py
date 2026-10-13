from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, Unicode
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime, new_id, now

DEFAULT_MEETING_NAME = "Lớp học trực tuyến"


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled','ongoing','ended')", name="ck_meeting_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(12), unique=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # First student who joined; informational only since rooms accept many students.
    student_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    mode: Mapped[str] = mapped_column(String(16), default="realtime", server_default="realtime")
    status: Mapped[str] = mapped_column(String(16), default="ongoing")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Room metadata merged from BE A.
    name: Mapped[str | None] = mapped_column(Unicode(100), default=DEFAULT_MEETING_NAME)
    description: Mapped[str | None] = mapped_column(Unicode(500), default="")
    tags: Mapped[list | None] = mapped_column(JSON, default=list)
    participant_mode: Mapped[str | None] = mapped_column(String(16), default="free")
    duration_minutes: Mapped[int | None] = mapped_column(Integer, default=45)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # BE A room-level recording (POST /recording, /recording-file). Video uploads through
    # /recordings use the Recording table; meeting output derives status from both.
    recording_status: Mapped[str | None] = mapped_column(String(16), default="none")
    recording_url: Mapped[str | None] = mapped_column(String(2048))
    recording_public_id: Mapped[str | None] = mapped_column(String(256), index=True)
    recording_resource_type: Mapped[str | None] = mapped_column(String(16))
    processing_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failed_reason: Mapped[str | None] = mapped_column(String(64))
    participants: Mapped[list["Participant"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (
        CheckConstraint("status IN ('joined','left','disconnected')", name="ck_participant_status"),
    )
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="joined")
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    left_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    disconnected_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
