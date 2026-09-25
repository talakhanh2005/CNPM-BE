from sqlalchemy import select, update

from app.core.db import lock_row, new_id, now
from app.core.errors import AppError
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

    def claim_student(self, meeting, user_id):
        # Reserve the same student for the lifetime of this one-to-one classroom.
        # Also check legacy memberships before assigning a previously absent slot.
        if any(p.user_id not in {meeting.teacher_id, user_id} for p in meeting.participants):
            raise AppError(409, "ROOM_FULL", "This classroom already has a student")
        if getattr(self.db, "is_mongo", False):
            claimed = self.db.collection("meetings").update_one(
                {
                    "id": meeting.id,
                    "status": "ongoing",
                    "$or": [{"student_id": None}, {"student_id": user_id}],
                },
                {"$set": {"student_id": user_id}},
            )
            if not claimed.matched_count:
                raise AppError(409, "ROOM_FULL", "Student slot unavailable")
        else:
            from app.core.db import compare_and_swap

            claimed = compare_and_swap(
                self.db,
                update(Meeting)
                .where(
                    Meeting.id == meeting.id,
                    Meeting.status == "ongoing",
                    (Meeting.student_id.is_(None)) | (Meeting.student_id == user_id),
                )
                .values(student_id=user_id),
                Meeting.id,
            )
            if not claimed:
                raise AppError(409, "ROOM_FULL", "Student slot unavailable")
        meeting.student_id = user_id

    def history(self, teacher_id, offset, limit, mode=None):
        if getattr(self.db, "is_mongo", False):
            query = {"teacher_id": teacher_id}
            if mode == "realtime":
                query["$or"] = [{"mode": "realtime"}, {"mode": {"$exists": False}}]
            elif mode:
                query["mode"] = mode
            return [
                model_from_doc(Meeting, doc)
                for doc in self.db.collection("meetings")
                .find(query)
                .sort([("created_at", -1), ("id", -1)])
                .skip(offset)
                .limit(limit)
            ]
        statement = select(Meeting).where(Meeting.teacher_id == teacher_id)
        if mode:
            statement = statement.where(Meeting.mode == mode)
        return self.db.scalars(
            statement.order_by(Meeting.created_at.desc(), Meeting.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()

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
