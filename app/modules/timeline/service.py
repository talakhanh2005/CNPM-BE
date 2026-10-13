import logging

from app.core.errors import AppError
from app.integrations.ai_schema import BatchResult
from app.modules.analysis.model import AnalysisResult
from app.modules.analysis.repository import AnalysisRepository
from app.modules.meetings.service import MeetingService
from app.modules.recordings.repository import RecordingRepository
from app.modules.timeline.repository import TimelineRepository
from app.modules.timeline.segments import build_segments
from app.modules.timeline.stats import clip, summarize

# Recording status -> data_status of contract v1 §2.
DATA_STATUS = {
    "uploaded": "QUEUED",
    "pending": "QUEUED",
    "processing": "PROCESSING",
    "completed": "COMPLETED",
    "failed": "FAILED",
}
logger = logging.getLogger(__name__)


def not_ready(data_status):
    return AppError(
        409,
        "ANALYSIS_NOT_READY",
        "Video analysis is not completed yet",
        [{"data_status": data_status}],
    )


def ingest(db, recording):
    """Store segments for a completed recording from its saved AI result (BE-TU-03)."""
    stored = db.get(AnalysisResult, recording.id)
    if stored is None:
        return None
    result = BatchResult.model_validate(stored.result)
    segments, source = build_segments(result, recording.duration)
    job = AnalysisRepository(db).get(recording.id)
    TimelineRepository(db).replace(
        recording, job.id if job else None, segments, result.model_version, source
    )
    return result


def ingest_recording(session_factory, recording_id):
    """Worker hook after a job completes; failures are logged and retried lazily on read."""
    try:
        with session_factory() as db:
            recording = RecordingRepository(db).get(recording_id)
            if recording is not None and recording.status == "completed":
                ingest(db, recording)
    except Exception:
        logger.exception("Timeline ingestion failed for recording %s", recording_id)


class TimelineService:
    def __init__(self, db):
        self.db, self.repo = db, TimelineRepository(db)

    def resolve(self, meeting_id, user, recording_id=None):
        """Contract D6/D7: owning teacher, after_session meeting, completed recording."""
        meeting = MeetingService(self.db).require(meeting_id, user, owner=True)
        if meeting.mode != "after_session":
            raise AppError(
                409, "INVALID_MEETING_MODE", "Timeline and chat exist only for after_session"
            )
        recordings = self.repo.recordings(meeting_id)
        if recording_id:
            recording = next((r for r in recordings if r.id == recording_id), None)
            if recording is None:
                raise AppError(404, "RECORDING_NOT_FOUND", "Recording not found in this meeting")
        else:
            recording = next((r for r in recordings if r.status == "completed"), None)
            recording = recording or (recordings[0] if recordings else None)
        if recording is None:
            raise not_ready("NO_RECORDING")
        if recording.status != "completed":
            raise not_ready(DATA_STATUS.get(recording.status, "QUEUED"))
        return meeting, recording

    def segments(self, recording):
        """Stored segments, building them on first read when ingestion has not run yet."""
        segments = self.repo.segments(recording.id)
        if not segments and ingest(self.db, recording) is not None:
            segments = self.repo.segments(recording.id)
        return segments

    def timeline(self, meeting_id, user, recording_id=None, start=None, end=None, student=None):
        meeting, recording = self.resolve(meeting_id, user, recording_id)
        duration = recording.duration
        start = 0.0 if start is None else start
        end = duration if end is None else min(end, duration)
        if end <= start and start < duration:
            raise AppError(422, "VALIDATION_ERROR", "from_seconds must be less than to_seconds")
        segments = self.segments(recording)
        if student:
            segments = [s for s in segments if s["student_id"] == student]
        window = clip(segments, start, end) if end > start else []
        job = AnalysisRepository(self.db).get(recording.id)
        return {
            "meeting_id": meeting.id,
            "recording_id": recording.id,
            "analysis_id": job.id if job else None,
            "model_version": next((s["model_version"] for s in segments), None),
            "duration_seconds": duration,
            "data_status": "COMPLETED",
            "segments_source": next((s["source"] for s in segments), None),
            "range": {"from_seconds": start, "to_seconds": max(start, end)},
            "segments": [
                {
                    "start_seconds": s["start_seconds"],
                    "end_seconds": s["end_seconds"],
                    "emotion": s["emotion"],
                    "avg_confidence": s["avg_confidence"],
                    "student_id": s["student_id"],
                }
                for s in window
            ],
            "summary": summarize(window, start, max(start, end)),
        }
