import secrets

from pymongo.errors import DuplicateKeyError
from sqlalchemy.exc import IntegrityError

from app.core.db import now
from app.core.errors import AppError
from app.modules.meetings.model import Meeting
from app.modules.meetings.repository import MeetingRepository


class MeetingService:
    """Shared meeting authorization contract for BE-03 through BE-07."""

    def __init__(self, db):
        self.db, self.repo = db, MeetingRepository(db)

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

    def create(self, user, data):
        if user.role != "teacher":
            raise AppError(403, "FORBIDDEN", "Teacher required")
        for _ in range(5):
            try:
                meeting = self.repo.add(
                    Meeting(
                        code=secrets.token_hex(5).upper(), teacher_id=user.id, status=data.status
                    )
                )
                self.repo.join(meeting.id, user.id)
                self.db.commit()
                self.db.refresh(meeting)
                return meeting
            except (IntegrityError, DuplicateKeyError):
                self.db.rollback()
        raise AppError(503, "CODE_UNAVAILABLE", "Unable to allocate meeting code")

    def join(self, meeting_id, user):
        meeting = self.repo.get(meeting_id, lock=True)
        if meeting is None:
            raise AppError(404, "MEETING_NOT_FOUND", "Meeting not found")
        if meeting.status != "ongoing":
            raise AppError(409, "MEETING_NOT_ACTIVE", "Meeting is not ongoing")
        if user.role == "teacher" and user.id != meeting.teacher_id:
            raise AppError(403, "FORBIDDEN", "Only the owning teacher or students may join")
        self.repo.join(meeting_id, user.id)
        self.db.commit()
        self.db.refresh(meeting)
        return meeting

    def join_code(self, code, user):
        meeting = self.repo.by_code(code)
        if not meeting:
            raise AppError(404, "MEETING_NOT_FOUND", "Meeting code not found")
        return self.join(meeting.id, user)

    def leave(self, meeting_id, user):
        meeting = self.require(meeting_id, user, lock=True)
        participant = self.repo.participant(meeting_id, user.id)
        if participant and participant.status != "left":
            participant.status, participant.left_at = "left", now()
        self.db.commit()
        self.db.refresh(meeting)
        return meeting

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

    def end(self, meeting_id, user):
        meeting = self.require(meeting_id, user, owner=True, lock=True)
        if meeting.status != "ended":
            meeting.status, meeting.ended_at = "ended", now()
            self.repo.leave_all(meeting_id)
        self.db.commit()
        self.db.refresh(meeting)
        return meeting
