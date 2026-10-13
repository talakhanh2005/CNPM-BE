from collections import Counter
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Emotion = Literal["happy", "neutral", "sad", "angry", "surprised", "fearful", "disgusted"]
EMOTIONS = ("happy", "neutral", "sad", "angry", "surprised", "fearful", "disgusted")


class EmotionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emotion: Emotion
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    mock: bool = False


class FrameResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame_id: str = Field(min_length=1, max_length=64)
    timestamp: datetime
    face_detected: bool
    emotion: Emotion | Literal["fail_detection"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    probabilities: dict[Emotion, Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]]
    face_id: str | None = Field(default=None, max_length=128)
    failure_reason: Literal["no_face", "ai_error"] | None = None
    mock: bool = False
    # Contract v1 §6.1: optional so older AI builds stay compatible.
    model_version: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def valid_detection(self):
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must include timezone")
        if set(self.probabilities) != set(EMOTIONS):
            raise ValueError("probabilities must contain all seven emotion classes")
        if self.face_detected:
            if self.emotion == "fail_detection" or not self.face_id or self.failure_reason:
                raise ValueError(
                    "Detected face requires emotion and face_id, without failure_reason"
                )
            if abs(sum(self.probabilities.values()) - 1) > 0.001:
                raise ValueError("Detected face probabilities must sum to one")
            if abs(self.probabilities[self.emotion] - self.confidence) > 0.001:
                raise ValueError("confidence must match the selected emotion probability")
            if self.confidence < max(self.probabilities.values()):
                raise ValueError("emotion must be a most probable class")
        else:
            if self.emotion != "fail_detection" or self.confidence != 0 or self.face_id:
                raise ValueError(
                    "Undetected face must have fail_detection, zero confidence, null face_id"
                )
            if any(self.probabilities.values()):
                raise ValueError("Undetected face probabilities must be zero")
            self.failure_reason = self.failure_reason or "no_face"
        return self

    @classmethod
    def failed(cls, frame_id, timestamp, reason="ai_error"):
        return cls(
            frame_id=frame_id,
            timestamp=timestamp,
            face_detected=False,
            emotion="fail_detection",
            confidence=0,
            probabilities=dict.fromkeys(EMOTIONS, 0.0),
            failure_reason=reason,
        )


class TimelinePoint(EmotionResult):
    timestamp: float = Field(ge=0, allow_inf_nan=False, description="Seconds from recording start")
    student_id: str | None = Field(default=None, max_length=36)


SegmentEmotion = Emotion | Literal["no_face", "unknown"]
SEGMENT_EMOTIONS = (*EMOTIONS, "no_face", "unknown")


class Segment(BaseModel):
    """Contract v1 §6.2: one [start, end) span of a video in seconds."""

    model_config = ConfigDict(extra="forbid")
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    emotion: SegmentEmotion
    avg_confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    student_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def valid_span(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Segment end_seconds must be greater than start_seconds")
        if self.emotion == "no_face" and self.avg_confidence is not None:
            raise ValueError("no_face segments have no confidence")
        return self


class BatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_counts: dict[Emotion, Annotated[int, Field(strict=True, ge=0, le=1000000000)]] = Field(
        description="Counts, not percentages; required for correct aggregation"
    )
    timeline: list[TimelinePoint] = Field(default_factory=list, max_length=20000)
    summary: str = Field(default="", max_length=4000)
    mock: bool = False
    # Contract v1 §6.2 (optional): smoothed segments; BE derives them when absent.
    segments: list[Segment] | None = Field(default=None, max_length=20000)
    model_version: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def counts_valid(self):
        timeline_counts = Counter(point.emotion for point in self.timeline)
        if any(
            count > self.sample_counts.get(emotion, 0) for emotion, count in timeline_counts.items()
        ):
            raise ValueError("Timeline must be a subset of the counted samples")
        return self

    @model_validator(mode="after")
    def segments_valid(self):
        # Per student, segments are sorted and never overlap: [start, end) spans.
        last_end = {}
        for segment in self.segments or []:
            previous = last_end.get(segment.student_id)
            if previous is not None and segment.start_seconds < previous - 1e-6:
                raise ValueError("Segments must be sorted and must not overlap")
            last_end[segment.student_id] = segment.end_seconds
        return self
