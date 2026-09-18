from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import ORMModel


class MeetingIn(BaseModel):
    status: Literal["scheduled", "ongoing"] = "ongoing"


class JoinCodeIn(BaseModel):
    code: str = Field(min_length=8, max_length=12, pattern="^[A-Za-z0-9]+$")


class ParticipantOut(ORMModel):
    user_id: str
    status: Literal["joined", "left"]
    joined_at: datetime
    left_at: datetime | None


class MeetingOut(ORMModel):
    id: str
    code: str
    teacher_id: str
    status: Literal["scheduled", "ongoing", "ended"]
    created_at: datetime
    ended_at: datetime | None
    participants: list[ParticipantOut]
