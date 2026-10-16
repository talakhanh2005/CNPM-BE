"""Test doubles. The application itself never fabricates AI output."""

import hashlib
import random

from app.integrations.ai_schema import EMOTIONS, BatchResult, FrameResult


class FakeAIClient:
    """Deterministic stand-in for the AI service in unit tests only."""

    async def analyze_video(self, recording_id, url, duration, idempotency_key):
        rng = random.Random(recording_id)
        timeline, counts = [], {emotion: 0 for emotion in EMOTIONS}
        for i in range(20):
            emotion = rng.choice(EMOTIONS)
            counts[emotion] += 1
            timeline.append(
                {
                    "timestamp": duration * i / 20,
                    "emotion": emotion,
                    "confidence": 0.8,
                    "mock": True,
                }
            )
        return BatchResult(
            sample_counts=counts,
            timeline=timeline,
            summary="MOCK: synthetic data for integration testing.",
            mock=True,
            model_version="mock",
        )

    async def analyze_frame(self, frame, content_type, frame_id, timestamp):
        rng = random.Random(hashlib.sha256(frame).digest())
        emotion = rng.choice(EMOTIONS)
        return FrameResult(
            frame_id=frame_id,
            timestamp=timestamp,
            emotion=emotion,
            confidence=0.8,
            face_detected=True,
            face_id="mock-face",
            probabilities={e: 0.8 if e == emotion else 0.2 / 6 for e in EMOTIONS},
            mock=True,
            model_version="mock",
        )
