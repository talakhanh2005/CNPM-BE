from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from app.core.document import Document, not_stored

DEFAULT_MEETING_NAME = "Lớp học trực tuyến"


@dataclass(kw_only=True, eq=False)
class Participant(Document):
    __collection__: ClassVar[str] = "participants"
    meeting_id: str | None = None
    user_id: str | None = None
    # joined | left | disconnected
    status: str | None = None
    joined_at: datetime | None = None
    left_at: datetime | None = None
    disconnected_at: datetime | None = None


@dataclass(kw_only=True, eq=False)
class Meeting(Document):
    __collection__: ClassVar[str] = "meetings"
    id: str | None = None
    code: str | None = None
    teacher_id: str | None = None
    # First student who joined; informational only since rooms accept many students.
    student_id: str | None = None
    # realtime | after_session
    mode: str | None = None
    # scheduled | ongoing | ended
    status: str | None = None
    created_at: datetime | None = None
    ended_at: datetime | None = None
    # Room metadata merged from BE A.
    name: str | None = None
    description: str | None = None
    tags: list | None = None
    participant_mode: str | None = None
    duration_minutes: int | None = None
    deleted_at: datetime | None = None
    # BE A room-level recording (POST /recording, /recording-file). Video uploads through
    # /recordings use the Recording collection; meeting output derives status from both.
    recording_status: str | None = None
    recording_url: str | None = None
    recording_public_id: str | None = None
    recording_resource_type: str | None = None
    processing_started_at: datetime | None = None
    failed_reason: str | None = None
    # Loaded from the participants collection; embedded copies are never written back.
    participants: list = not_stored(list)

    @property
    def student_ids(self):
        """Every student membership, including students who already left (BE Tiền)."""
        return sorted(p.user_id for p in self.participants if p.user_id != self.teacher_id)
