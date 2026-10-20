from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.core.db import new_id, now
from app.modules.auth.model import User


@dataclass(kw_only=True)
class Meeting:
    __collection__: ClassVar[str] = "meetings"
    id: str = field(default_factory=new_id)
    code: str
    teacher_id: str
    student_id: str | None = None
    mode: str = "realtime"
    status: str = "ongoing"
    created_at: datetime = field(default_factory=now)
    ended_at: datetime | None = None
    participants: list[Participant] = field(default_factory=list, metadata={"persist": False})

    @property
    def student_ids(self):
        return sorted(p.user_id for p in self.participants if p.user_id != self.teacher_id)


@dataclass(kw_only=True)
class Participant:
    __collection__: ClassVar[str] = "participants"
    meeting_id: str
    user_id: str
    status: str = "joined"
    joined_at: datetime = field(default_factory=now)
    left_at: datetime | None = None
    user: User | None = field(default=None, metadata={"persist": False})

    @property
    def full_name(self):
        return self.user.full_name if self.user is not None else None
