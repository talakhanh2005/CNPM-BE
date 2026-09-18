from sqlalchemy import select

from app.core.db import lock_row, new_id, now
from app.modules.recordings.model import Recording


class RecordingRepository:
    def __init__(self, db):
        self.db = db

    def get(self, recording_id, lock=False):
        if getattr(self.db, "is_mongo", False):
            return self.db.get(Recording, recording_id)
        statement = select(Recording).where(Recording.id == recording_id)
        if lock:
            statement = lock_row(statement, Recording, self.db)
        return self.db.scalar(statement)

    def add(self, **values):
        values.setdefault("id", new_id())
        values.setdefault("status", "uploaded")
        values.setdefault("created_at", now())
        recording = Recording(**values)
        self.db.add(recording)
        self.db.flush()
        return recording
