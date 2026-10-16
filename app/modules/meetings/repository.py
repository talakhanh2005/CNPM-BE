from app.core.db import new_id, now
from app.core.mongo import model_from_doc
from app.modules.auth.model import User
from app.modules.meetings.model import Meeting, Participant


class MeetingRepository:
    def __init__(self, db):
        self.db = db

    def get(self, meeting_id, lock=False, include_deleted=False):
        # Soft-deleted meetings (BE A DELETE) behave as missing everywhere.
        meeting = self.db.get(Meeting, meeting_id)
        if meeting is not None and meeting.deleted_at is not None and not include_deleted:
            return None
        return meeting

    def _with_participants(self, meeting):
        if meeting is not None:
            meeting.participants = self.db.participants_of(meeting.id)
        return meeting

    def by_code(self, code):
        meeting = model_from_doc(
            Meeting,
            self.db.collection("meetings").find_one({"code": code.upper(), "deleted_at": None}),
        )
        return self._with_participants(meeting)

    def participant(self, meeting_id, user_id):
        return self.db.get(Participant, (meeting_id, user_id))

    def history(self, teacher_id, offset, limit, mode=None):
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

    def visible_to(self, user):
        """BE A ownership: a teacher sees hosted meetings, a student sees joined meetings."""
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

    def has_recording(self, meeting_id):
        return self.db.collection("recordings").count_documents({"meeting_id": meeting_id}) > 0

    def by_recording_public_id(self, public_id):
        doc = self.db.collection("meetings").find_one(
            {"recording_public_id": public_id, "deleted_at": None}, {"id": 1}
        )
        return self.db.get(Meeting, doc["id"]) if doc else None

    def users(self, user_ids):
        """id -> User for participant names; one query per call."""
        user_ids = list(set(user_ids))
        if not user_ids:
            return {}
        return {
            doc["id"]: model_from_doc(User, doc)
            for doc in self.db.collection("users").find({"id": {"$in": user_ids}})
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
        self.db.collection("participants").update_many(
            {"meeting_id": meeting_id, "status": {"$in": ["joined", "disconnected"]}},
            {"$set": {"status": "left", "left_at": now()}},
        )
