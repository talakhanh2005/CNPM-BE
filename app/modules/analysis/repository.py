from datetime import timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.db import compare_and_swap, lock_row, new_id, now
from app.core.mongo import model_from_doc
from app.modules.analysis.model import AnalysisJob, AnalysisResult
from app.modules.recordings.model import Recording


class AnalysisRepository:
    def __init__(self, db):
        self.db = db

    def get(self, recording_id):
        if getattr(self.db, "is_mongo", False):
            return model_from_doc(
                AnalysisJob,
                self.db.collection("analysis_jobs").find_one({"recording_id": recording_id}),
            )
        return self.db.scalar(select(AnalysisJob).where(AnalysisJob.recording_id == recording_id))

    def enqueue(self, recording):
        if getattr(self.db, "is_mongo", False):
            changed = self.db.collection("recordings").update_one(
                {"id": recording.id, "status": {"$in": ["uploaded", "failed"]}},
                {"$set": {"status": "pending"}},
            ).modified_count == 1
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
        changed = compare_and_swap(
            self.db,
            update(Recording)
            .where(Recording.id == recording.id, Recording.status.in_(("uploaded", "failed")))
            .values(status="pending"),
            Recording.id,
        )
        job = self.get(recording.id)
        if job:
            if changed or job.state == "failed":
                job.state = "pending"
                job.error_message = None
                job.lease_until = None
                job.lease_token = None
                job.updated_at = now()
                self.db.flush()
            return job
        if not changed:
            recording = self.db.get(Recording, recording.id)
            if recording is None or recording.status not in {"uploaded", "failed", "pending"}:
                return None
            recording.status = "pending"
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
        self.db.add(job)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            return self.get(recording.id)
        return job

    def claim(self, lease_seconds):
        if getattr(self.db, "is_mongo", False):
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
        token = new_id()
        cutoff = now()
        statement = (
            select(AnalysisJob)
            .where(
                or_(
                    AnalysisJob.state == "pending",
                    (AnalysisJob.state == "processing") & (AnalysisJob.lease_until < cutoff),
                )
            )
            .order_by(AnalysisJob.created_at, AnalysisJob.id)
            .limit(1)
        )
        statement = lock_row(statement, AnalysisJob, self.db)
        job = self.db.scalar(statement)
        if not job:
            return None
        claimed = compare_and_swap(
            self.db,
            update(AnalysisJob)
            .where(
                AnalysisJob.id == job.id,
                or_(
                    AnalysisJob.state == "pending",
                    (AnalysisJob.state == "processing") & (AnalysisJob.lease_until < cutoff),
                ),
            )
            .values(
                state="processing",
                lease_token=token,
                lease_until=now() + timedelta(seconds=lease_seconds),
                updated_at=now(),
                error_message=None,
                attempts=AnalysisJob.attempts + 1,
            ),
            AnalysisJob.id,
        )
        if not claimed:
            return None
        self.db.execute(
            update(Recording).where(Recording.id == job.recording_id).values(status="processing")
        )
        self.db.flush()
        self.db.refresh(job)
        self.db.commit()
        return job

    def finish(self, job_id, token, result=None, error=None):
        if getattr(self.db, "is_mongo", False):
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
        state = "failed" if error else "completed"
        finished = compare_and_swap(
            self.db,
            update(AnalysisJob)
            .where(
                AnalysisJob.id == job_id,
                AnalysisJob.state == "processing",
                AnalysisJob.lease_token == token,
            )
            .values(
                state=state,
                lease_token=None,
                lease_until=None,
                error_message=error,
                updated_at=now(),
            ),
            AnalysisJob.id,
        )
        if not finished:
            return False
        job = self.db.get(AnalysisJob, job_id)
        recording_id = job.recording_id
        self.db.execute(update(Recording).where(Recording.id == recording_id).values(status=state))
        if not error:
            self.db.merge(
                AnalysisResult(recording_id=recording_id, result=result, completed_at=now())
            )
        self.db.commit()
        return True
