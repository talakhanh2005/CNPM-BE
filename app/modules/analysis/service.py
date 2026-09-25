import asyncio
import logging

from app.modules.analysis.repository import AnalysisRepository
from app.modules.meetings.model import Participant
from app.modules.recordings.repository import RecordingRepository
from app.modules.recordings.service import RecordingService


class AnalysisService:
    def __init__(self, db):
        self.db, self.repo = db, AnalysisRepository(db)

    def status(self, recording_id, user):
        recording = RecordingService(self.db).require(recording_id, user)
        job = self.repo.get(recording_id)
        return {
            "recording_id": recording.id,
            "status": recording.status,
            "job_id": job.id if job else None,
            "attempts": job.attempts if job else 0,
            "error_message": job.error_message if job else None,
            "updated_at": job.updated_at if job else recording.created_at,
        }

    def enqueue(self, recording_id, user):
        recording = RecordingService(self.db).require(recording_id, user, lock=True)
        self.repo.enqueue(recording)
        self.db.commit()
        self.db.expire_all()
        return self.status(recording_id, user)


async def process_one(session_factory, ai, storage, settings):
    """Durable at-least-once worker; CAS lease prevents stale result overwrites."""
    with session_factory() as db:
        AnalysisRepository(db).recover_after_session()
        job = AnalysisRepository(db).claim(settings.job_lease_seconds)
        if not job:
            return False
        recording = RecordingRepository(db).get(job.recording_id)
        job_id, token = job.id, job.lease_token
        recording_id, duration, meeting_id = recording.id, recording.duration, recording.meeting_id
        public_id, format = recording.public_id, recording.format
    try:
        async with asyncio.timeout(settings.ai_timeout_seconds):
            url = storage.download_url(public_id, format, settings.ai_timeout_seconds + 120)
            result = await ai.analyze_video(recording_id, url, duration, job_id)
        if any(point.timestamp > duration for point in result.timeline):
            raise ValueError("AI timeline exceeds recording duration")
        with session_factory() as db:
            for student_id in {p.student_id for p in result.timeline if p.student_id}:
                if db.get(Participant, (meeting_id, student_id)) is None:
                    raise ValueError("AI returned a student outside the meeting")
            AnalysisRepository(db).finish(job_id, token, result=result.model_dump(mode="json"))
    except Exception as exc:
        logging.getLogger(__name__).warning("AI job %s failed (%s)", job_id, type(exc).__name__)
        with session_factory() as db:
            AnalysisRepository(db).finish(
                job_id, token, error="AI processing failed or timed out; retry analysis"
            )
    return True
