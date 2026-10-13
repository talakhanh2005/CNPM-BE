from sqlalchemy import select, update

from app.core.db import lock_row, new_id, now
from app.core.mongo import model_from_doc
from app.modules.auth.model import User
from app.modules.meetings.model import Meeting, Participant


class MeetingRepository:
    def __init__(self, db):
        self.db = db

    @property
    def mongo(self):
        return getattr(self.db, "is_mongo", False)

    def get(self, meeting_id, lock=False, include_deleted=False):
        # Soft-deleted meetings (BE A DELETE) behave as missing everywhere.
        if self.mongo:
            meeting = self.db.get(Meeting, meeting_id)
        else:
            statement = select(Meeting).where(Meeting.id == meeting_id)
            if lock:
                statement = lock_row(statement, Meeting, self.db)
            meeting = self.db.scalar(statement)
        if meeting is not None and meeting.deleted_at is not None and not include_deleted:
            return None
        return meeting

    def _with_participants(self, meeting):
        if meeting is not None:
            participants = list(self.db.collection("participants").find({"meeting_id": meeting.id}))
            meeting.participants = [model_from_doc(Participant, item) for item in participants]
        return meeting

    def by_code(self, code):
        if self.mongo:
            meeting = model_from_doc(
                Meeting,
                self.db.collection("meetings").find_one({"code": code.upper(), "deleted_at": None}),
            )
            return self._with_participants(meeting)
        return self.db.scalar(
            select(Meeting).where(Meeting.code == code.upper(), Meeting.deleted_at.is_(None))
        )

    def participant(self, meeting_id, user_id):
        return self.db.get(Participant, (meeting_id, user_id))

    def history(self, teacher_id, offset, limit, mode=None):
        if self.mongo:
            query = {"teacher_id": teacher_id, "deleted_at": None}
            if mode == "realtime":
                query["$or"] = [{"mode": "realtime"}, {"mode": {"$exists": False}}]
            elif mode:
                query["mode"] = mode
            return [
                self._with_participants(model_from_doc(Meeting, doc))
                for doc in self.db.collection("meetings")
                .find(query)
                .sort([("created_at", -1), ("id", -1)])
                .skip(offset)
                .limit(limit)
            ]
        statement = select(Meeting).where(
            Meeting.teacher_id == teacher_id, Meeting.deleted_at.is_(None)
        )
        if mode:
            statement = statement.where(Meeting.mode == mode)
        return self.db.scalars(
            statement.order_by(Meeting.created_at.desc(), Meeting.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()

    def visible_to(self, user):
        """BE A ownership: a teacher sees hosted meetings, a student sees joined meetings."""
        if self.mongo:
            if user.role == "teacher":
                query = {"teacher_id": user.id}
            else:
                ids = [
                    item["meeting_id"]
                    for item in self.db.collection("participants").find({"user_id": user.id})
                ]
                query = {"id": {"$in": ids}}
            query["deleted_at"] = None
            # db.get returns session-tracked instances, so later changes are persisted.
            return [
                self.db.get(Meeting, doc["id"])
                for doc in self.db.collection("meetings")
                .find(query, {"id": 1})
                .sort([("created_at", -1), ("id", -1)])
            ]
        statement = select(Meeting).where(Meeting.deleted_at.is_(None))
        if user.role == "teacher":
            statement = statement.where(Meeting.teacher_id == user.id)
        else:
            statement = statement.where(
                Meeting.id.in_(select(Participant.meeting_id).where(Participant.user_id == user.id))
            )
        return self.db.scalars(
            statement.order_by(Meeting.created_at.desc(), Meeting.id.desc())
        ).all()

    def by_recording_public_id(self, public_id):
        if self.mongo:
            doc = self.db.collection("meetings").find_one(
                {"recording_public_id": public_id, "deleted_at": None}, {"id": 1}
            )
            return self.db.get(Meeting, doc["id"]) if doc else None
        return self.db.scalar(
            select(Meeting).where(
                Meeting.recording_public_id == public_id, Meeting.deleted_at.is_(None)
            )
        )

    def users(self, user_ids):
        """id -> User for participant names; one query per call."""
        user_ids = list(set(user_ids))
        if not user_ids:
            return {}
        if self.mongo:
            return {
                doc["id"]: model_from_doc(User, doc)
                for doc in self.db.collection("users").find({"id": {"$in": user_ids}})
            }
        return {
            user.id: user for user in self.db.scalars(select(User).where(User.id.in_(user_ids)))
        }

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
                disconnected_at=None,
            )
            self.db.add(participant)
        elif participant.status != "joined":
            participant.status, participant.joined_at = "joined", now()
            participant.left_at = participant.disconnected_at = None
        self.db.flush()
        return participant

    def leave_all(self, meeting_id):
        if self.mongo:
            self.db.collection("participants").update_many(
                {"meeting_id": meeting_id, "status": {"$in": ["joined", "disconnected"]}},
                {"$set": {"status": "left", "left_at": now()}},
            )
            return
        self.db.execute(
            update(Participant)
            .where(
                Participant.meeting_id == meeting_id,
                Participant.status.in_(["joined", "disconnected"]),
            )
            .values(status="left", left_at=now())
        )
