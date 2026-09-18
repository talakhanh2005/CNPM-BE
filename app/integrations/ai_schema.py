from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Emotion = Literal["happy", "neutral", "sad", "angry", "surprised", "fearful", "disgusted"]
EMOTIONS = ("happy", "neutral", "sad", "angry", "surprised", "fearful", "disgusted")


class EmotionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emotion: Emotion
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    mock: bool = False


class TimelinePoint(EmotionResult):
    timestamp: float = Field(ge=0, allow_inf_nan=False, description="Seconds from recording start")
    student_id: str | None = Field(default=None, max_length=36)


class BatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_counts: dict[Emotion, Annotated[int, Field(strict=True, ge=0, le=1000000000)]] = Field(
        description="Counts, not percentages; required for correct aggregation"
    )
    timeline: list[TimelinePoint] = Field(default_factory=list, max_length=20000)
    summary: str = Field(default="", max_length=4000)
    mock: bool = False

    @model_validator(mode="after")
    def counts_valid(self):
        timeline_counts = Counter(point.emotion for point in self.timeline)
        if any(
            count > self.sample_counts.get(emotion, 0) for emotion, count in timeline_counts.items()
        ):
            raise ValueError("Timeline must be a subset of the counted samples")
        return self
