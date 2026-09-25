from collections import Counter

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
        stored = self.repo.analysis(recording_id)
        if not stored:
            return self.pack({}, [], 0, selection, "none", recording.status)
        result = BatchResult.model_validate(stored.result)
        timeline = sorted(result.timeline, key=lambda p: p.timestamp)
        return self.pack(
            result.sample_counts,
            [
                {**p.model_dump(), "recording_id": recording_id}
                for p in timeline[selection.offset : selection.offset + selection.limit]
            ],
            len(timeline),
            selection,
            "batch",
            recording.status,
            result.summary,
            result.mock,
        )

    def meeting(self, meeting_id, user, selection):
        MeetingService(self.db).require(meeting_id, user, owner=True)
        statuses = self.repo.statuses(meeting_id)
        batches = (
            self.repo.batch_results(meeting_id) if selection.source in {"auto", "batch"} else []
        )
        if batches:
            counts, timeline, mock = Counter(), [], False
            for stored, recording in batches:
                result = BatchResult.model_validate(stored.result)
                counts.update(result.sample_counts)
                timeline.extend(
                    {**p.model_dump(), "recording_id": recording.id}
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
                meeting_id, selection.offset, selection.limit
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
