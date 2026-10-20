from app.core.db import new_id, now
from app.core.mongo import model_from_doc
from app.modules.emotions.model import EmotionSample


class EmotionRepository:
    def __init__(self, db):
        self.db = db

    def add(self, **values):
        values.setdefault("id", new_id())
        values.setdefault("timestamp", now())
        sample = EmotionSample(**values)
        self.db.add(sample)
        self.db.flush()
        return sample

    def by_frame(self, meeting_id, student_id, frame_id):
        return model_from_doc(
            EmotionSample,
            self.db.collection("emotion_samples").find_one(
                {"meeting_id": meeting_id, "student_id": student_id, "frame_id": frame_id}
            ),
        )

    def latest(self, meeting_id, student_id, logged=False):
        query = {"meeting_id": meeting_id, "student_id": student_id}
        if logged:
            query["logged"] = {"$ne": False}
        return model_from_doc(
            EmotionSample,
            self.db.collection("emotion_samples").find_one(
                query, sort=[("received_at", -1), ("timestamp", -1), ("id", -1)]
            ),
        )

    def delete(self, meeting_id, sample_id):
        self.db.collection("emotion_samples").delete_one(
            {"id": sample_id, "meeting_id": meeting_id}
        )
