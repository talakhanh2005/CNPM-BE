from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import ORMModel


class MeetingIn(BaseModel):
    status: Literal["scheduled", "ongoing"] = "ongoing"
    mode: Literal["realtime", "after_session"] = "realtime"


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
    student_id: str | None = None
    mode: Literal["realtime", "after_session"] = "realtime"
    status: Literal["scheduled", "ongoing", "ended"]
    created_at: datetime
    ended_at: datetime | None
    participants: list[ParticipantOut]


class MeetingHistoryItem(BaseModel):
    id: str
    code: str
    mode: Literal["realtime", "after_session"]
    status: Literal["scheduled", "ongoing", "ended"]
    student_id: str | None
    created_at: datetime
    ended_at: datetime | None
    recording_statuses: dict[str, int]
    analysis_status: Literal[
        "not_required",
        "awaiting_recording",
        "awaiting_analysis",
        "pending",
        "processing",
        "completed",
        "failed",
    ]
    report_url: str


class MeetingHistoryOut(BaseModel):
    items: list[MeetingHistoryItem]
    offset: int
    limit: int


class IceConfigOut(BaseModel):
    iceServers: list[dict]
    turn_configured: bool
