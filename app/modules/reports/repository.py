from sqlalchemy import func, select, true

from app.core.mongo import model_from_doc
from app.modules.analysis.model import AnalysisResult
from app.modules.emotions.model import EmotionSample
from app.modules.recordings.model import Recording


class ReportRepository:
    def __init__(self, db):
        self.db = db

    def analysis(self, recording_id):
        return self.db.get(AnalysisResult, recording_id)

    def batch_results(self, meeting_id):
        if getattr(self.db, "is_mongo", False):
            recordings = list(
                self.db.collection("recordings")
                .find({"meeting_id": meeting_id, "status": "completed"})
                .sort([("created_at", 1), ("id", 1)])
            )
            rows = []
            for recording_doc in recordings:
                result_doc = self.db.collection("analysis_results").find_one(
                    {"recording_id": recording_doc["id"]}
                )
                if result_doc:
                    rows.append(
                        (
                            model_from_doc(AnalysisResult, result_doc),
                            model_from_doc(Recording, recording_doc),
                        )
                    )
            return rows
        return list(
            self.db.execute(
                select(AnalysisResult, Recording)
                .join(Recording, Recording.id == AnalysisResult.recording_id)
                .where(Recording.meeting_id == meeting_id, Recording.status == "completed")
                .order_by(Recording.created_at, Recording.id)
            ).all()
        )

    def statuses(self, meeting_id):
        if getattr(self.db, "is_mongo", False):
            return {
                item["_id"]: item["count"]
                for item in self.db.collection("recordings").aggregate(
                    [
                        {"$match": {"meeting_id": meeting_id}},
                        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
                    ]
                )
            }
        return dict(
            self.db.execute(
                select(Recording.status, func.count())
                .where(Recording.meeting_id == meeting_id)
                .group_by(Recording.status)
            ).all()
        )

    def realtime(self, meeting_id, offset, limit):
        if getattr(self.db, "is_mongo", False):
            counts = {
                item["_id"]: item["count"]
                for item in self.db.collection("emotion_samples").aggregate(
                    [
                        {"$match": {"meeting_id": meeting_id}},
                        {"$group": {"_id": "$emotion", "count": {"$sum": 1}}},
                    ]
                )
            }
            samples = [
                model_from_doc(EmotionSample, doc)
                for doc in self.db.collection("emotion_samples")
                .find({"meeting_id": meeting_id})
                .sort([("timestamp", 1), ("id", 1)])
                .skip(offset)
                .limit(limit)
            ]
            mock = (
                self.db.collection("emotion_samples").count_documents(
                    {"meeting_id": meeting_id, "mock": True}
                )
                > 0
            )
            return counts, samples, mock
        counts = dict(
            self.db.execute(
                select(EmotionSample.emotion, func.count())
                .where(EmotionSample.meeting_id == meeting_id)
                .group_by(EmotionSample.emotion)
            ).all()
        )
        samples = self.db.scalars(
            select(EmotionSample)
            .where(EmotionSample.meeting_id == meeting_id)
            .order_by(EmotionSample.timestamp, EmotionSample.id)
            .offset(offset)
            .limit(limit)
        ).all()
        mock = self.db.scalar(
            select(func.count())
            .select_from(EmotionSample)
            .where(EmotionSample.meeting_id == meeting_id, EmotionSample.mock == true())
        )
        return counts, samples, mock > 0
