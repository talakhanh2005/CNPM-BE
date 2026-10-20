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
        recordings = (
            self.db.collection("recordings")
            .find({"meeting_id": meeting_id, "status": "completed"})
            .sort([("created_at", 1), ("id", 1)])
        )
        rows = []
        for doc in recordings:
            result = self.db.collection("analysis_results").find_one({"recording_id": doc["id"]})
            if result:
                rows.append(
                    (model_from_doc(AnalysisResult, result), model_from_doc(Recording, doc))
                )
        return rows

    def statuses(self, meeting_id):
        return {
            item["_id"]: item["count"]
            for item in self.db.collection("recordings").aggregate(
                [
                    {"$match": {"meeting_id": meeting_id}},
                    {"$group": {"_id": "$status", "count": {"$sum": 1}}},
                ]
            )
        }

    def realtime(self, meeting_id, offset, limit):
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
