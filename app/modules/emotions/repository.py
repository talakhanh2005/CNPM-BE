from sqlalchemy import select

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

    def latest(self, meeting_id, student_id, logged=False):
        if getattr(self.db, "is_mongo", False):
            query = {"meeting_id": meeting_id, "student_id": student_id}
            if logged:
                query["logged"] = {"$ne": False}
            return model_from_doc(
                EmotionSample,
                self.db.collection("emotion_samples").find_one(
                    query, sort=[("received_at", -1), ("timestamp", -1), ("id", -1)]
                ),
            )
        query = select(EmotionSample).where(
            EmotionSample.meeting_id == meeting_id, EmotionSample.student_id == student_id
        )
        if logged:
            query = query.where(EmotionSample.logged.is_(True))
        return self.db.scalar(
            query.order_by(
                EmotionSample.received_at.desc(),
                EmotionSample.timestamp.desc(),
                EmotionSample.id.desc(),
            ).limit(1)
        )

    def logs(self, meeting_id, offset, limit):
        if getattr(self.db, "is_mongo", False):
            return [
                model_from_doc(EmotionSample, doc)
                for doc in self.db.collection("emotion_samples")
                .find({"meeting_id": meeting_id, "logged": {"$ne": False}})
                .sort([("received_at", 1), ("id", 1)])
                .skip(offset)
                .limit(limit)
            ]
        return self.db.scalars(
            select(EmotionSample)
            .where(EmotionSample.meeting_id == meeting_id, EmotionSample.logged.is_(True))
            .order_by(EmotionSample.received_at, EmotionSample.id)
            .offset(offset)
            .limit(limit)
        ).all()
