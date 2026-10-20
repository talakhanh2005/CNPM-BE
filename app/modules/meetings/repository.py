from app.core.db import new_id, now
from app.modules.meetings.model import Meeting, Participant


class MeetingRepository:
    def __init__(self, db):
        self.db = db

    def get(self, meeting_id, lock=False):
        return self.db.get(Meeting, meeting_id)

    def by_code(self, code):
        doc = self.db.collection("meetings").find_one({"code": code.upper()})
        return self.get(doc["id"]) if doc else None

    def participant(self, meeting_id, user_id):
        return self.db.get(Participant, (meeting_id, user_id))

    def history(self, teacher_id, offset, limit, mode=None):
        query = {"teacher_id": teacher_id}
        if mode == "realtime":
            query["$or"] = [{"mode": "realtime"}, {"mode": {"$exists": False}}]
        elif mode:
            query["mode"] = mode
        return [
            self.get(doc["id"])
            for doc in self.db.collection("meetings")
            .find(query)
            .sort([("created_at", -1), ("id", -1)])
            .skip(offset)
            .limit(limit)
        ]

    def add(self, meeting):
        meeting.id = meeting.id or new_id()
        meeting.created_at = meeting.created_at or now()
        meeting.status = meeting.status or "ongoing"
        meeting.participants = []
        self.db.add(meeting)
        self.db.flush()
        return meeting

    def join(self, meeting_id, user_id):
        participant = self.participant(meeting_id, user_id)
        if participant is None:
            participant = Participant(meeting_id=meeting_id, user_id=user_id)
            self.db.add(participant)
        elif participant.status == "left":
            participant.status, participant.joined_at, participant.left_at = "joined", now(), None
        self.db.flush()
        return participant

    def leave_all(self, meeting_id):
        self.db.collection("participants").update_many(
            {"meeting_id": meeting_id, "status": "joined"},
            {"$set": {"status": "left", "left_at": now()}},
        )

    def delete(self, meeting_id):
        """Remove the meeting and all documents owned by it."""
        recording_ids = [
            doc["id"] for doc in self.db.collection("recordings").find({"meeting_id": meeting_id})
        ]
        for name in ("analysis_jobs", "analysis_results"):
            self.db.collection(name).delete_many({"recording_id": {"$in": recording_ids}})
        for name in ("emotion_samples", "materials", "recordings", "participants"):
            self.db.collection(name).delete_many({"meeting_id": meeting_id})
        self.db.collection("meetings").delete_one({"id": meeting_id})
