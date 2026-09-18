from app.core.db import new_id, now
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
