from datetime import timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.db import new_id, now
from app.core.mongo import model_from_doc
from app.modules.analysis.model import AnalysisJob, AnalysisResult
from app.modules.recordings.model import Recording


class AnalysisRepository:
    def __init__(self, db):
        self.db = db

    def get(self, recording_id):
        return model_from_doc(
            AnalysisJob,
            self.db.collection("analysis_jobs").find_one({"recording_id": recording_id}),
        )

    def recover_after_session(self):
        """Repair a crash between committing a video and inserting its automatic job."""
        docs = self.db.collection("recordings").aggregate(
            [
                {"$match": {"status": {"$in": ["uploaded", "pending"]}}},
                {
                    "$lookup": {
                        "from": "meetings",
                        "localField": "meeting_id",
                        "foreignField": "id",
                        "as": "meeting",
                    }
                },
                {"$match": {"meeting.mode": "after_session"}},
                {
                    "$lookup": {
                        "from": "analysis_jobs",
                        "localField": "id",
                        "foreignField": "recording_id",
                        "as": "jobs",
                    }
                },
                {"$match": {"jobs": {"$size": 0}}},
                {"$limit": 50},
                {"$project": {"meeting": 0, "jobs": 0}},
            ]
        )
        for recording in [model_from_doc(Recording, doc) for doc in docs]:
            self.enqueue(recording)
        self.db.commit()

    def enqueue(self, recording):
        changed = (
            self.db.collection("recordings")
            .update_one(
                {"id": recording.id, "status": {"$in": ["uploaded", "failed"]}},
                {"$set": {"status": "pending"}},
            )
            .modified_count
            == 1
        )
        job = self.get(recording.id)
        if job:
            if changed or job.state == "failed":
                self.db.collection("analysis_jobs").update_one(
                    {"id": job.id},
                    {
                        "$set": {
                            "state": "pending",
                            "error_message": None,
                            "lease_until": None,
                            "lease_token": None,
                            "updated_at": now(),
                        }
                    },
                )
                return self.get(recording.id)
            return job
        if not changed:
            recording = self.db.get(Recording, recording.id)
            if recording is None or recording.status not in {"uploaded", "failed", "pending"}:
                return None
            recording.status = "pending"
            self.db.flush()
        job = AnalysisJob(
            id=new_id(),
            recording_id=recording.id,
            state="pending",
            attempts=0,
            lease_token=None,
            lease_until=None,
            error_message=None,
            created_at=now(),
            updated_at=now(),
        )
        try:
            self.db.add(job)
            self.db.flush()
        except DuplicateKeyError:
            self.db.rollback()
            return self.get(recording.id)
        return job

    def claim(self, lease_seconds):
        """Atomically take the oldest pending job, or one whose lease has expired."""
        token = new_id()
        cutoff = now()
        lease_until = now() + timedelta(seconds=lease_seconds)
        doc = self.db.collection("analysis_jobs").find_one_and_update(
            {
                "$or": [
                    {"state": "pending"},
                    {"state": "processing", "lease_until": {"$lt": cutoff}},
                ]
            },
            {
                "$set": {
                    "state": "processing",
                    "lease_token": token,
                    "lease_until": lease_until,
                    "updated_at": now(),
                    "error_message": None,
                },
                "$inc": {"attempts": 1},
            },
            sort=[("created_at", 1), ("id", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        job = model_from_doc(AnalysisJob, doc)
        self.db.collection("recordings").update_one(
            {"id": job.recording_id}, {"$set": {"status": "processing"}}
        )
        return job

    def finish(self, job_id, token, result=None, error=None):
        state = "failed" if error else "completed"
        updated = self.db.collection("analysis_jobs").find_one_and_update(
            {"id": job_id, "state": "processing", "lease_token": token},
            {
                "$set": {
                    "state": state,
                    "lease_token": None,
                    "lease_until": None,
                    "error_message": error,
                    "updated_at": now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            return False
        job = model_from_doc(AnalysisJob, updated)
        self.db.collection("recordings").update_one(
            {"id": job.recording_id}, {"$set": {"status": state}}
        )
        if not error:
            self.db.merge(
                AnalysisResult(recording_id=job.recording_id, result=result, completed_at=now())
            )
        return True
