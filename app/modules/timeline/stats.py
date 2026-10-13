"""Statistics shared by timeline, chat and the report/analytics APIs (contract v1 §5.4)."""

from app.integrations.ai_schema import EMOTIONS


def clip(segments, start, end):
    """Segments intersecting [start, end), cut to that range; input order is kept."""
    clipped = []
    for segment in segments:
        lo, hi = max(segment["start_seconds"], start), min(segment["end_seconds"], end)
        if hi > lo:
            clipped.append({**segment, "start_seconds": round(lo, 3), "end_seconds": round(hi, 3)})
    return clipped


def summarize(segments, start, end):
    """Seconds and percent per emotion over analysed time only; no_face/unknown never count
    as neutral. ``coverage`` is analysed time divided by the range length."""
    total = max(0.0, end - start)
    seconds = {emotion: 0.0 for emotion in EMOTIONS}
    no_face = unknown = 0.0
    for segment in clip(segments, start, end):
        length = segment["end_seconds"] - segment["start_seconds"]
        if segment["emotion"] in seconds:
            seconds[segment["emotion"]] += length
        elif segment["emotion"] == "no_face":
            no_face += length
        else:
            unknown += length
    analyzed = sum(seconds.values())
    emotions = {
        emotion: {
            "seconds": round(value, 3),
            "percent": round(value * 100 / analyzed, 2) if analyzed else 0.0,
        }
        for emotion, value in sorted(seconds.items(), key=lambda item: -item[1])
        if value > 0
    }
    return {
        "total_seconds": round(total, 3),
        "analyzed_seconds": round(analyzed, 3),
        "no_face_seconds": round(no_face, 3),
        "unknown_seconds": round(unknown, 3),
        "coverage": round(analyzed / total, 4) if total else 0.0,
        "emotions": emotions,
        "dominant_emotion": next(iter(emotions), None),
    }
