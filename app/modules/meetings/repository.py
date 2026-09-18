from sqlalchemy import select, update

from app.core.db import lock_row, new_id, now
from app.core.mongo import model_from_doc
from app.modules.meetings.model import Meeting, Participant


class MeetingRepository:
    def __init__(self, db):
        self.db = db

    def get(self, meeting_id, lock=False):
        if getattr(self.db, "is_mongo", False):
            return self.db.get(Meeting, meeting_id)
        statement = select(Meeting).where(Meeting.id == meeting_id)
        if lock:
            statement = lock_row(statement, Meeting, self.db)
        return self.db.scalar(statement)

    def by_code(self, code):
        if getattr(self.db, "is_mongo", False):
            meeting = model_from_doc(
                Meeting, self.db.collection("meetings").find_one({"code": code.upper()})
            )
            if meeting is not None:
                participants = list(
                    self.db.collection("participants").find({"meeting_id": meeting.id})
                )
                meeting.participants = [model_from_doc(Participant, item) for item in participants]
            return meeting
        return self.db.scalar(select(Meeting).where(Meeting.code == code.upper()))

    def participant(self, meeting_id, user_id):
        return self.db.get(Participant, (meeting_id, user_id))

    def add(self, meeting):
        if meeting.id is None:
            meeting.id = new_id()
        if meeting.created_at is None:
            meeting.created_at = now()
        meeting.status = meeting.status or "ongoing"
        meeting.participants = []
        self.db.add(meeting)
        self.db.flush()
        return meeting

    def join(self, meeting_id, user_id):
        participant = self.participant(meeting_id, user_id)
        if participant is None:
            participant = Participant(
                meeting_id=meeting_id,
                user_id=user_id,
                status="joined",
                joined_at=now(),
                left_at=None,
            )
            self.db.add(participant)
        elif participant.status == "left":
            participant.status, participant.joined_at, participant.left_at = "joined", now(), None
        self.db.flush()
        return participant

    def leave_all(self, meeting_id):
        if getattr(self.db, "is_mongo", False):
            self.db.collection("participants").update_many(
                {"meeting_id": meeting_id, "status": "joined"},
                {"$set": {"status": "left", "left_at": now()}},
            )
            return
        self.db.execute(
            update(Participant)
            .where(Participant.meeting_id == meeting_id, Participant.status == "joined")
            .values(status="left", left_at=now())
        )
