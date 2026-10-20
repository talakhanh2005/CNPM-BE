from collections import Counter

from app.core.errors import AppError
from app.integrations.ai_schema import EMOTIONS, BatchResult
from app.modules.meetings.service import MeetingService
from app.modules.recordings.service import RecordingService
from app.modules.reports.repository import ReportRepository


class ReportService:
    def __init__(self, db):
        self.db, self.repo = db, ReportRepository(db)

    def pack(
        self,
        counts,
        timeline,
        total,
        selection,
        source,
        status,
        summary="",
        mock=False,
        statuses=None,
    ):
        counts = {key: value for key, value in counts.items() if key in EMOTIONS}
        sample_count = sum(counts.values())
        return {
            "distribution": {k: round(v * 100 / sample_count, 4) for k, v in counts.items()}
            if sample_count
            else {},
            "sample_counts": dict(counts),
            "sample_count": sample_count,
            "timeline": timeline,
            "timeline_total": total,
            "offset": selection.offset,
            "limit": selection.limit,
            "summary": summary
            or (
                f"{sample_count} classified samples."
                if sample_count
                else "No analysis data available."
            ),
            "source": source,
            "time_basis": {"batch": "recording_seconds", "realtime": "utc", "none": "none"}[source],
            "status": status,
            "recording_statuses": statuses or {},
            "mock": mock,
        }

    def recording(self, recording_id, user, selection):
        recording = RecordingService(self.db).require(recording_id, user)
        # The stored recording decides who the video belongs to, never the AI payload (BE Tiền).
        identity = {
            "meeting_id": recording.meeting_id,
            "recording_id": recording.id,
            "student_id": recording.student_id,
        }
        stored = self.repo.analysis(recording_id)
        if not stored:
            return {**self.pack({}, [], 0, selection, "none", recording.status), **identity}
        result = BatchResult.model_validate(stored.result)
        timeline = sorted(result.timeline, key=lambda p: p.timestamp)
        report = self.pack(
            result.sample_counts,
            [
                {**p.model_dump(), "recording_id": recording_id, "student_id": recording.student_id}
                for p in timeline[selection.offset : selection.offset + selection.limit]
            ],
            len(timeline),
            selection,
            "batch",
            recording.status,
            result.summary,
            result.mock,
        )
        return {**report, **identity}

    def meeting(self, meeting_id, user, selection):
        return {**self._meeting(meeting_id, user, selection), "meeting_id": meeting_id}

    def _meeting(self, meeting_id, user, selection):
        meeting = MeetingService(self.db).require(meeting_id, user, owner=True)
        if meeting.mode != "after_session":
            # README 1.2: a Report exists only for post-session analysis (contract v1 section 4).
            raise AppError(409, "INVALID_MEETING_MODE", "Report exists only for after_session")
        statuses = self.repo.statuses(meeting_id)
        batches = (
            self.repo.batch_results(meeting_id) if selection.source in {"auto", "batch"} else []
        )
        if selection.student_id:
            # Each recording is one student's camera, so a student filter keeps their videos.
            batches = [row for row in batches if row[1].student_id == selection.student_id]
        if batches:
            # Sum sample counts across recordings, never average per-recording percentages.
            counts, timeline, mock = Counter(), [], False
            for stored, recording in batches:
                result = BatchResult.model_validate(stored.result)
                counts.update(result.sample_counts)
                timeline.extend(
                    {
                        **p.model_dump(),
                        "recording_id": recording.id,
                        "student_id": recording.student_id,
                    }
                    for p in sorted(result.timeline, key=lambda p: p.timestamp)
                )
                mock |= result.mock
            status = (
                "partial"
                if any(k != "completed" and v for k, v in statuses.items())
                else "completed"
            )
            return self.pack(
                counts,
                timeline[selection.offset : selection.offset + selection.limit],
                len(timeline),
                selection,
                "batch",
                status,
                mock=mock,
                statuses=statuses,
            )
        if selection.source != "batch":
            counts, samples, mock = self.repo.realtime(
                meeting_id, selection.offset, selection.limit, selection.student_id
            )
            timeline = [
                {
                    "timestamp": s.timestamp,
                    "student_id": s.student_id,
                    "emotion": s.emotion,
                    "confidence": s.confidence,
                    "sample_id": s.id,
                    "mock": s.mock,
                    "probabilities": s.probabilities,
                    "face_id": s.face_id,
                    "face_detected": s.face_detected if s.face_detected is not None else True,
                    "frame_id": s.frame_id,
                    "failure_reason": s.failure_reason,
                }
                for s in samples
            ]
            return self.pack(
                counts,
                timeline,
                sum(counts.values()),
                selection,
                "realtime" if counts else "none",
                "available" if counts else "empty",
                mock=mock,
                statuses=statuses,
            )
        return self.pack({}, [], 0, selection, "none", "empty", statuses=statuses)
