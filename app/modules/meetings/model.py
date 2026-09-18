from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime, new_id, now


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled','ongoing','ended')", name="ck_meeting_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(12), unique=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ongoing")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    participants: Mapped[list["Participant"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (CheckConstraint("status IN ('joined','left')", name="ck_participant_status"),)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="joined")
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    left_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
