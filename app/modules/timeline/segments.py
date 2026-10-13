"""Turn an AI video result into non-overlapping [start, end) segments (contract v1 §6.2-6.3)."""

from collections import Counter, defaultdict
from statistics import median

EPSILON = 1e-6


def _merge(segments):
    """Join touching segments of the same student and emotion; confidence weighted by length."""
    merged = []
    for segment in segments:
        last = merged[-1] if merged else None
        if (
            last
            and last["student_id"] == segment["student_id"]
            and last["emotion"] == segment["emotion"]
            and abs(last["end_seconds"] - segment["start_seconds"]) <= EPSILON
        ):
            length_a = last["end_seconds"] - last["start_seconds"]
            length_b = segment["end_seconds"] - segment["start_seconds"]
            if last["avg_confidence"] is not None and segment["avg_confidence"] is not None:
                last["avg_confidence"] = (
                    last["avg_confidence"] * length_a + segment["avg_confidence"] * length_b
                ) / (length_a + length_b)
            else:
                last["avg_confidence"] = last["avg_confidence"] or segment["avg_confidence"]
            last["end_seconds"] = segment["end_seconds"]
            if last["sample_count"] is not None or segment["sample_count"] is not None:
                last["sample_count"] = (last["sample_count"] or 0) + (segment["sample_count"] or 0)
            continue
        merged.append(dict(segment))
    for segment in merged:
        if segment["avg_confidence"] is not None:
            segment["avg_confidence"] = round(segment["avg_confidence"], 4)
    return merged


def _segment(start, end, emotion, confidence, student_id, samples=None):
    return {
        "start_seconds": round(start, 3),
        "end_seconds": round(end, 3),
        "emotion": emotion,
        "avg_confidence": confidence,
        "student_id": student_id,
        "sample_count": samples,
    }


def _derive_one(points, duration, student_id):
    """Points of one student -> segments covering [0, duration); gaps become no_face."""
    by_time = defaultdict(list)
    for point in points:
        by_time[point.timestamp].append(point)
    samples = []
    for timestamp in sorted(by_time):
        group = by_time[timestamp]
        counts = Counter(point.emotion for point in group)
        top = max(counts.values())
        # Majority label; ties go to the most confident prediction.
        best = max(
            (point for point in group if counts[point.emotion] == top),
            key=lambda point: point.confidence,
        )
        confidence = sum(p.confidence for p in group if p.emotion == best.emotion) / top
        samples.append((timestamp, best.emotion, confidence))
    if not samples:
        return [_segment(0, duration, "no_face", None, student_id)] if duration > 0 else []

    gaps = [b[0] - a[0] for a, b in zip(samples, samples[1:]) if b[0] - a[0] > EPSILON]
    step = median(gaps) if gaps else 1.0
    segments, cursor = [], 0.0
    for index, (timestamp, emotion, confidence) in enumerate(samples):
        if timestamp >= duration:
            break
        if timestamp - cursor >= 0.5 * step:
            segments.append(_segment(cursor, timestamp, "no_face", None, student_id))
            start = timestamp
        else:
            start = cursor
        following = samples[index + 1][0] if index + 1 < len(samples) else None
        if following is not None and following - timestamp <= 1.5 * step:
            end = following
        else:
            end = timestamp + step
        end = min(end, duration)
        if end - start > EPSILON:
            segments.append(_segment(start, end, emotion, confidence, student_id, 1))
            cursor = end
    if duration - cursor >= 0.5 * step:
        segments.append(_segment(cursor, duration, "no_face", None, student_id))
    elif segments and duration - cursor > EPSILON:
        segments[-1]["end_seconds"] = round(duration, 3)
    return _merge(segments)


def build_segments(result, duration):
    """Return (segments, source). AI segments win; otherwise derive them from timeline points."""
    if result.segments:
        segments = [
            _segment(
                s.start_seconds,
                min(s.end_seconds, duration) if duration else s.end_seconds,
                s.emotion,
                s.avg_confidence,
                s.student_id,
            )
            for s in result.segments
            if not duration or s.start_seconds < duration
        ]
        ordered = sorted(segments, key=lambda s: (s["student_id"] or "", s["start_seconds"]))
        return _merge(ordered), "ai"
    by_student = defaultdict(list)
    for point in result.timeline:
        by_student[point.student_id].append(point)
    if not by_student:
        by_student[None] = []
    segments = []
    for student_id in sorted(by_student, key=lambda key: key or ""):
        segments.extend(_derive_one(by_student[student_id], duration, student_id))
    return segments, "derived"
