import secrets
from datetime import timedelta

from pymongo.errors import DuplicateKeyError

from app.core.concurrency import meeting_operation
from app.core.db import now
from app.core.errors import AppError
from app.modules.meetings.model import DEFAULT_MEETING_NAME, Meeting
from app.modules.meetings.repository import MeetingRepository

# BE A: without an AI result, room-level "processing" turns "failed" after five minutes.
PROCESSING_TIMEOUT = timedelta(minutes=5)
FAILED_REASON_TIMEOUT = "timeout_waiting_ai"
# BE A history filter accepted active/closed; they map onto BE B statuses.
STATUS_ALIASES = {"active": "ongoing", "closed": "ended"}


def not_found():
    # BE A answers 404 instead of 403 so outsiders cannot probe which meetings exist.
    return AppError(404, "ROOM_NOT_FOUND", "Không tìm thấy")


def as_utc(value):
    from datetime import timezone

    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def derived_recording_status(meeting, statuses):
    """BE B Recording rows win; otherwise BE A's room-level status."""
    if statuses:
        if statuses.get("failed"):
            return "failed"
        if statuses.get("processing") or statuses.get("pending"):
            return "processing"
        if statuses.get("uploaded"):
            return "uploaded"
        return "completed"
    return meeting.recording_status or "none"


class MeetingService:
    """Shared meeting authorization contract for BE-03 through BE-07."""

    def __init__(self, db, settings=None):
        self.db, self.repo, self.settings = db, MeetingRepository(db), settings

    def require(self, meeting_id, user, owner=False, active=False, lock=False):
        meeting = self.repo.get(meeting_id, lock)
        if meeting is None:
            raise AppError(404, "MEETING_NOT_FOUND", "Meeting not found")
        participant = self.repo.participant(meeting_id, user.id)
        if owner and meeting.teacher_id != user.id:
            raise AppError(403, "FORBIDDEN", "Only the owning teacher can access this resource")
        if not owner and meeting.teacher_id != user.id and not participant:
            raise AppError(403, "NOT_A_PARTICIPANT", "Join the meeting first")
        if active and (
            meeting.status != "ongoing" or not participant or participant.status != "joined"
        ):
            raise AppError(
                409, "MEETING_NOT_ACTIVE", "An ongoing meeting and joined membership are required"
            )
        return meeting

    @staticmethod
    def require_recording_mode(meeting):
        """README section 1.2: only after_session meetings may store video (T02)."""
        if meeting.mode != "after_session":
            raise AppError(
                409,
                "INVALID_MEETING_MODE",
                "Recording and video storage are only allowed in after_session meetings",
            )

    def require_owner_or_404(self, meeting_id, user):
        meeting = self.repo.get(meeting_id)
        if meeting is None or user.role != "teacher" or meeting.teacher_id != user.id:
            raise not_found()
        return meeting

    def create(self, user, data):
        if user.role != "teacher":
            raise AppError(403, "FORBIDDEN", "Teacher required")
        name = (data.name or "").strip() or DEFAULT_MEETING_NAME
        for _ in range(5):
            try:
                meeting = self.repo.add(
                    Meeting(
                        code=secrets.token_hex(5).upper(),
                        teacher_id=user.id,
                        status=data.status,
                        mode=data.resolved_mode(),
                        name=name,
                        description=(data.description or "").strip(),
                        tags=data.tags or [],
                        participant_mode=data.participant_mode,
                        duration_minutes=data.duration_minutes,
                        recording_status="none",
                    )
                )
                self.repo.join(meeting.id, user.id)
                self.db.commit()
                self.db.refresh(meeting)
                return meeting
            except DuplicateKeyError:
                self.db.rollback()
        raise AppError(503, "CODE_UNAVAILABLE", "Unable to allocate meeting code")

    def student_count(self, meeting):
        return sum(
            1
            for p in meeting.participants
            if p.user_id != meeting.teacher_id and p.status in {"joined", "disconnected"}
        )

    @meeting_operation
    def join(self, meeting_id, user):
        meeting = self.repo.get(meeting_id, lock=True)
        if meeting is None:
            raise AppError(404, "MEETING_NOT_FOUND", "Meeting not found")
        if meeting.status != "ongoing":
            raise AppError(409, "MEETING_NOT_ACTIVE", "Meeting is not ongoing")
        if user.role != "student" and user.id != meeting.teacher_id:
            raise AppError(403, "FORBIDDEN", "Only the owning teacher or students may join")
        if user.role == "student":
            current = self.repo.participant(meeting_id, user.id)
            already_in = current is not None and current.status in {"joined", "disconnected"}
            # The room holds one teacher plus students, bounded like the signaling sockets.
            limit = self.settings.max_room_connections if self.settings else 30
            if not already_in and self.student_count(meeting) + 1 >= limit:
                raise AppError(409, "ROOM_FULL", "This classroom is full")
            if meeting.student_id is None:
                meeting.student_id = user.id  # first student; informational
        self.repo.join(meeting_id, user.id)
        self.db.commit()
        self.db.refresh(meeting)
        return meeting

    def lookup_code(self, code, user):
        """Check a room code without joining: same rules as join, no side effects (U09)."""
        meeting = self.repo.by_code(code)
        if not meeting:
            raise AppError(404, "MEETING_NOT_FOUND", "Meeting code not found")
        if meeting.status != "ongoing":
            raise AppError(409, "MEETING_NOT_ACTIVE", "Meeting is not ongoing")
        if user.role != "student" and user.id != meeting.teacher_id:
            raise AppError(403, "FORBIDDEN", "Only the owning teacher or students may join")
        return {
            "id": meeting.id,
            "code": meeting.code,
            "name": meeting.name,
            "mode": meeting.mode or "realtime",
            "status": meeting.status,
        }

    def join_code(self, code, user):
        meeting = self.repo.by_code(code)
        if not meeting:
            raise AppError(404, "MEETING_NOT_FOUND", "Meeting code not found")
        return self.join(meeting.id, user)

    @meeting_operation
    def leave(self, meeting_id, user):
        meeting = self.require(meeting_id, user, lock=True)
        participant = self.repo.participant(meeting_id, user.id)
        if participant and participant.status != "left":
            participant.status, participant.left_at = "left", now()
        self.db.commit()
        self.db.refresh(meeting)
        return meeting

    @meeting_operation
    def rejoin_if_disconnected(self, meeting_id, user):
        """BE A: opening a room again after a page exit restores the membership."""
        meeting = self.require(meeting_id, user)
        participant = self.repo.participant(meeting_id, user.id)
        if participant and participant.status == "disconnected" and meeting.status == "ongoing":
            participant.status, participant.joined_at = "joined", now()
            participant.disconnected_at = None
            self.db.commit()
            self.db.refresh(meeting)
        return meeting

    @meeting_operation
    def disconnect(self, meeting_id, user):
        """BE A: page exit marks the member disconnected (not left) so a refresh can return."""
        meeting = self.repo.get(meeting_id)
        if meeting is None or meeting.status != "ongoing":
            raise AppError(404, "ROOM_NOT_FOUND", "Không tìm thấy phòng đang hoạt động.")
        participant = self.repo.participant(meeting_id, user.id)
        if participant is None or participant.status == "left":
            return {"meeting_id": meeting_id, "user_id": user.id, "status": "ignored"}
        participant.status, participant.disconnected_at = "disconnected", now()
        self.db.commit()
        return {"meeting_id": meeting_id, "user_id": user.id, "status": "disconnected"}

    @meeting_operation
    def start(self, meeting_id, user):
        meeting = self.require(meeting_id, user, owner=True, lock=True)
        if meeting.status == "ended":
            raise AppError(409, "MEETING_ENDED", "Ended meetings cannot be restarted")
        meeting.status = "ongoing"
        meeting.ended_at = None
        self.repo.join(meeting_id, user.id)
        self.db.commit()
        self.db.refresh(meeting)
        return meeting

    @meeting_operation
    def end(self, meeting_id, user):
        meeting = self.require(meeting_id, user, owner=True, lock=True)
        if meeting.status != "ended":
            meeting.status, meeting.ended_at = "ended", now()
            self.repo.leave_all(meeting_id)
        self.db.commit()
        self.db.refresh(meeting)
        return meeting

    def update(self, meeting_id, user, data):
        """BE A PUT: owner edits name/description/tags; others get 404."""
        meeting = self.require_owner_or_404(meeting_id, user)
        values = data.model_dump(exclude_none=True)
        if not values:
            raise AppError(
                422, "VALIDATION_ERROR", "Provide at least one of name, description, tags"
            )
        for key, value in values.items():
            setattr(meeting, key, value)
        self.db.commit()
        self.db.refresh(meeting)
        return meeting

    def soft_delete(self, meeting_id, user):
        """BE A DELETE: keep the row, hide it from every lookup."""
        meeting = self.require_owner_or_404(meeting_id, user)
        meeting.deleted_at = now()
        self.db.commit()
        return {"meeting_id": meeting.id, "deleted_at": meeting.deleted_at}

    def can_record(self, meeting, user):
        if meeting.teacher_id == user.id:
            return True
        participant = self.repo.participant(meeting.id, user.id)
        return participant is not None and participant.status == "joined"

    def mark_recording_processing(self, meeting_id, user, duration_seconds):
        """BE A POST /recording: store duration and wait for an analysis result."""
        meeting = self.repo.get(meeting_id)
        if meeting is None or not self.can_record(meeting, user):
            raise not_found()
        self.require_recording_mode(meeting)
        if not meeting.recording_public_id and not self.repo.has_recording(meeting_id):
            # Without an uploaded video this would show "processing" forever.
            raise AppError(
                409, "RECORDING_NOT_UPLOADED", "Upload the video before saving its metadata"
            )
        seconds = 60 if duration_seconds is None else duration_seconds
        meeting.duration_minutes = max(1, round(seconds / 60))
        meeting.recording_status = "processing"
        meeting.processing_started_at = now()
        meeting.failed_reason = None
        self.db.commit()
        self.db.refresh(meeting)
        return meeting

    def expire_stale_processing(self, meeting):
        if meeting.recording_status != "processing" or not meeting.processing_started_at:
            return False
        if now() - as_utc(meeting.processing_started_at) <= PROCESSING_TIMEOUT:
            return False
        meeting.recording_status = "failed"
        meeting.failed_reason = FAILED_REASON_TIMEOUT
        self.db.commit()
        return True

    def history(self, user, q=None, status=None, recording_status=None, start=None, end=None):
        """BE A history: ownership, filters and newest first (pagination done by caller)."""
        from app.modules.reports.repository import ReportRepository

        status = STATUS_ALIASES.get(status, status)
        needle = (q or "").strip().casefold()
        reports = ReportRepository(self.db)
        items = []
        for meeting in self.repo.visible_to(user):
            self.expire_stale_processing(meeting)
            created = as_utc(meeting.created_at)
            if needle and needle not in (meeting.name or DEFAULT_MEETING_NAME).casefold():
                continue
            if status and meeting.status != status:
                continue
            if start is not None and created < start[0]:
                continue
            if end is not None:
                # A date-only to_date covers that whole day (BE A rule).
                end_value, date_only = end
                if created >= end_value + timedelta(days=1) if date_only else created > end_value:
                    continue
            current = derived_recording_status(meeting, reports.statuses(meeting.id))
            if recording_status and current != recording_status:
                continue
            items.append(meeting)
        return items


def meeting_out(db, meeting):
    """MeetingOut payload with participant names and the derived recording status."""
    from app.modules.reports.repository import ReportRepository

    repo = MeetingRepository(db)
    MeetingService(db).expire_stale_processing(meeting)
    users = repo.users([p.user_id for p in meeting.participants])
    statuses = ReportRepository(db).statuses(meeting.id)
    return {
        "id": meeting.id,
        "code": meeting.code,
        "teacher_id": meeting.teacher_id,
        "student_id": meeting.student_id,
        "mode": meeting.mode or "realtime",
        "status": meeting.status,
        "created_at": meeting.created_at,
        "ended_at": meeting.ended_at,
        "name": meeting.name or DEFAULT_MEETING_NAME,
        "description": meeting.description or "",
        "tags": meeting.tags or [],
        "participant_mode": meeting.participant_mode or "free",
        "duration_minutes": meeting.duration_minutes or 45,
        "recording_status": derived_recording_status(meeting, statuses),
        "recording_url": meeting.recording_url,
        "failed_reason": meeting.failed_reason,
        "participants": [
            {
                "user_id": p.user_id,
                "status": p.status,
                "joined_at": p.joined_at,
                "left_at": p.left_at,
                "disconnected_at": p.disconnected_at,
                "full_name": users[p.user_id].full_name if p.user_id in users else None,
                "role": users[p.user_id].role if p.user_id in users else None,
            }
            for p in meeting.participants
        ],
    }
