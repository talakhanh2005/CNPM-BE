from app.core.db import new_id, now
from app.modules.recordings.model import Recording


class RecordingRepository:
    def __init__(self, db):
        self.db = db

    def get(self, recording_id, lock=False):
        return self.db.get(Recording, recording_id)

    def add(self, **values):
        values.setdefault("id", new_id())
        values.setdefault("status", "uploaded")
        values.setdefault("created_at", now())
        recording = Recording(**values)
        self.db.add(recording)
        self.db.flush()
        return recording
