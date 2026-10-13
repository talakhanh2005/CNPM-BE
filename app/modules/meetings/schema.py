from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator

from app.core.schemas import ORMModel

MAX_NAME_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 500
MAX_TAGS = 10
MAX_TAG_LENGTH = 30


def clean_tags(tags):
    if tags is None:
        return None
    # Drop duplicates while keeping order (BE A rule).
    cleaned = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
    if len(cleaned) > MAX_TAGS or any(len(tag) > MAX_TAG_LENGTH for tag in cleaned):
        raise ValueError(f"At most {MAX_TAGS} tags of up to {MAX_TAG_LENGTH} characters")
    return cleaned


class MeetingIn(BaseModel):
    status: Literal["scheduled", "ongoing"] = "ongoing"
    mode: Literal["realtime", "after_session"] | None = None
    # BE A fields; camelCase names from the old classroom API are still accepted.
    name: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    tags: list[str] | None = None
    participant_mode: Literal["free", "approval"] = Field(
        default="free", validation_alias=AliasChoices("participant_mode", "participantMode")
    )
    duration_minutes: int = Field(
        default=45,
        ge=1,
        le=24 * 60,
        validation_alias=AliasChoices("duration_minutes", "durationMinutes"),
    )
    analysis_mode: Literal["realtime", "batch"] | None = Field(
        default=None, validation_alias=AliasChoices("analysis_mode", "analysisMode")
    )
    emotion_recognition: bool | None = Field(
        default=None, validation_alias=AliasChoices("emotion_recognition", "emotionRecognition")
    )

    _tags = field_validator("tags")(clean_tags)

    def resolved_mode(self):
        """mode wins; else BE A analysisMode/emotionRecognition; default realtime."""
        if self.mode:
            return self.mode
        if self.analysis_mode:
            return "realtime" if self.analysis_mode == "realtime" else "after_session"
        if self.emotion_recognition is False:
            return "after_session"
        return "realtime"


class MeetingUpdate(BaseModel):
    """BE A PUT /meetings/{id}: only name, description and tags can change."""

    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value or len(value) > MAX_NAME_LENGTH:
            raise ValueError(f"Name must be 1-{MAX_NAME_LENGTH} characters")
        return value

    @field_validator("description")
    @classmethod
    def valid_description(cls, value):
        if value is not None and len(value) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(f"Description must be at most {MAX_DESCRIPTION_LENGTH} characters")
        return value.strip() if value is not None else None

    _tags = field_validator("tags")(clean_tags)


class RecordingMetaIn(BaseModel):
    """BE A POST /meetings/{id}/recording body."""

    duration_seconds: float | None = Field(
        default=None, ge=0, validation_alias=AliasChoices("duration_seconds", "durationSeconds")
    )


class JoinCodeIn(BaseModel):
    code: str = Field(min_length=8, max_length=12, pattern="^[A-Za-z0-9]+$")


class ParticipantOut(ORMModel):
    user_id: str
    status: Literal["joined", "left", "disconnected"]
    joined_at: datetime
    left_at: datetime | None
    disconnected_at: datetime | None = None
    full_name: str | None = None
    role: str | None = None


class MeetingOut(ORMModel):
    id: str
    code: str
    teacher_id: str
    student_id: str | None = None
    mode: Literal["realtime", "after_session"] = "realtime"
    status: Literal["scheduled", "ongoing", "ended"]
    created_at: datetime
    ended_at: datetime | None
    name: str
    description: str = ""
    tags: list[str] = []
    participant_mode: Literal["free", "approval"] = "free"
    duration_minutes: int = 45
    recording_status: str = "none"
    recording_url: str | None = None
    failed_reason: str | None = None
    participants: list[ParticipantOut]


class MeetingHistoryItem(BaseModel):
    id: str
    code: str
    name: str
    mode: Literal["realtime", "after_session"]
    status: Literal["scheduled", "ongoing", "ended"]
    student_id: str | None
    created_at: datetime
    ended_at: datetime | None
    participant_count: int = 0
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
