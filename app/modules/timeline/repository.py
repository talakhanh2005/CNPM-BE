from sqlalchemy import delete, select

from app.core.db import new_id, now
from app.core.mongo import model_from_doc
from app.modules.recordings.model import Recording
from app.modules.timeline.model import EmotionSegment


def as_dict(segment):
    return {
        "start_seconds": segment.start_seconds,
        "end_seconds": segment.end_seconds,
        "emotion": segment.emotion,
        "avg_confidence": segment.avg_confidence,
        "student_id": segment.student_id,
        "sample_count": segment.sample_count,
        "model_version": segment.model_version,
        "source": segment.source,
    }


class TimelineRepository:
    def __init__(self, db):
        self.db = db

    @property
    def mongo(self):
        return getattr(self.db, "is_mongo", False)

    def recordings(self, meeting_id):
        """Recordings of a meeting, newest first (read only; the table belongs to BE-04)."""
        if self.mongo:
            return [
                model_from_doc(Recording, doc)
                for doc in self.db.collection("recordings")
                .find({"meeting_id": meeting_id})
                .sort([("created_at", -1), ("id", -1)])
            ]
        return self.db.scalars(
            select(Recording)
            .where(Recording.meeting_id == meeting_id)
            .order_by(Recording.created_at.desc(), Recording.id.desc())
        ).all()

    def segments(self, recording_id):
        if self.mongo:
            docs = (
                self.db.collection("emotion_segments")
                .find({"recording_id": recording_id})
                .sort([("student_id", 1), ("start_seconds", 1)])
            )
            return [as_dict(model_from_doc(EmotionSegment, doc)) for doc in docs]
        rows = self.db.scalars(
            select(EmotionSegment)
            .where(EmotionSegment.recording_id == recording_id)
            .order_by(EmotionSegment.student_id, EmotionSegment.start_seconds)
        ).all()
        return [as_dict(row) for row in rows]

    def replace(self, recording, job_id, segments, model_version, source):
        """Delete then insert all segments of one recording: re-running never duplicates."""
        rows = [
            {
                "id": new_id(),
                "analysis_job_id": job_id,
                "recording_id": recording.id,
                "meeting_id": recording.meeting_id,
                "start_seconds": segment["start_seconds"],
                "end_seconds": segment["end_seconds"],
                "emotion": segment["emotion"],
                "avg_confidence": segment["avg_confidence"],
                "student_id": segment["student_id"],
                "sample_count": segment["sample_count"],
                "model_version": model_version,
                "source": source,
                "created_at": now(),
            }
            for segment in segments
        ]
        if self.mongo:
            collection = self.db.collection("emotion_segments")
            collection.delete_many({"recording_id": recording.id})
            if rows:
                collection.insert_many(rows)
            return
        self.db.execute(delete(EmotionSegment).where(EmotionSegment.recording_id == recording.id))
        self.db.add_all(EmotionSegment(**row) for row in rows)
        self.db.commit()
