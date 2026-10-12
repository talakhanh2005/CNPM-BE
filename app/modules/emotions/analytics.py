from collections import Counter, defaultdict
from datetime import timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select

from app.core.db import now
from app.core.errors import AppError
from app.core.mongo import model_from_doc
from app.integrations.ai_schema import EMOTIONS
from app.modules.emotions.model import EmotionSample


def selected_samples(
    db, meeting_id, student_id=None, start=None, end=None, logged=False, offset=None, limit=None
):
    if start and end and start > end:
        raise AppError(422, "INVALID_TIME_RANGE", "start must be before end")
    if getattr(db, "is_mongo", False):
        query = {"meeting_id": meeting_id}
        if student_id:
            query["student_id"] = student_id
        if start or end:
            query["timestamp"] = {}
            if start:
                query["timestamp"]["$gte"] = start
            if end:
                query["timestamp"]["$lte"] = end
        if logged:
            query["logged"] = {"$ne": False}
        collection = db.collection("emotion_samples")
        cursor = collection.find(query).sort([("timestamp", 1), ("id", 1)])
        if offset is not None:
            total = collection.count_documents(query)
            return [
                model_from_doc(EmotionSample, d) for d in cursor.skip(offset).limit(limit)
            ], total
        return [model_from_doc(EmotionSample, d) for d in cursor]
    query = select(EmotionSample).where(EmotionSample.meeting_id == meeting_id)
    if student_id:
        query = query.where(EmotionSample.student_id == student_id)
    if start:
        query = query.where(EmotionSample.timestamp >= start)
    if end:
        query = query.where(EmotionSample.timestamp <= end)
    if logged:
        query = query.where(EmotionSample.logged.is_(True))
    ordered = query.order_by(EmotionSample.timestamp, EmotionSample.id)
    if offset is not None:
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        return db.scalars(ordered.offset(offset).limit(limit)).all(), total
    return db.scalars(ordered).all()


def summarize(samples):
    classified = [s for s in samples if s.emotion in EMOTIONS and s.face_detected]
    counts = Counter(s.emotion for s in classified)
    total = len(classified)
    positive = counts["happy"]
    negative = sum(counts[e] for e in ("angry", "disgusted", "fearful", "sad"))
    return {
        "sample_count": total,
        "total_samples": len(samples),
        "failed_samples": len(samples) - total,
        "sample_counts": {e: counts[e] for e in EMOTIONS},
        "distribution": {e: round(100 * counts[e] / total, 4) if total else 0 for e in EMOTIONS},
        "average_confidence": round(sum(s.confidence for s in classified) / total, 6)
        if total
        else None,
        "average_probabilities": {
            e: round(sum((s.probabilities or {}).get(e, 0) for s in classified) / total, 6)
            if total
            else 0
            for e in EMOTIONS
        },
        "positive_ratio": positive / total if total else 0,
        "negative_ratio": negative / total if total else 0,
        "neutral_ratio": (counts["neutral"] + counts["surprised"]) / total if total else 0,
        "positive_negative_ratio": positive / negative if negative else None,
    }


def dashboard(db, meeting_id, student_id=None, start=None, end=None, bucket_seconds=60):
    samples = selected_samples(db, meeting_id, student_id, start, end)
    students, buckets = defaultdict(list), defaultdict(list)
    for sample in samples:
        students[sample.student_id].append(sample)
        stamp = sample.timestamp
        bucket = stamp - timedelta(seconds=stamp.timestamp() % bucket_seconds)
        buckets[bucket].append(sample)
    return {
        "meeting_id": meeting_id,
        "student_id": student_id,
        "start": start,
        "end": end,
        "bucket_seconds": bucket_seconds,
        **summarize(samples),
        "students": [
            {"student_id": sid, **summarize(rows)} for sid, rows in sorted(students.items())
        ],
        "trend": [
            {"timestamp": stamp, **summarize(rows)} for stamp, rows in sorted(buckets.items())
        ],
    }


def realtime_summary(factory, meeting_id, window_seconds):
    end = now()
    with factory() as db:
        return jsonable_encoder(
            {
                "type": "EMOTION_AGGREGATE",
                "window_seconds": window_seconds,
                **dashboard(db, meeting_id, start=end - timedelta(seconds=window_seconds), end=end),
            }
        )
