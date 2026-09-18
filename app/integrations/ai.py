import hashlib
import random
from typing import Protocol

import httpx

from app.integrations.ai_schema import EMOTIONS, BatchResult, EmotionResult


class AIClient(Protocol):
    async def analyze_video(
        self, recording_id: str, url: str, duration: float, idempotency_key: str
    ) -> BatchResult: ...
    async def analyze_frame(self, frame: bytes, content_type: str) -> EmotionResult: ...


class MockAIClient:
    """Synthetic seeded-random output. Never represents actual emotion inference."""

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
        )

    async def analyze_frame(self, frame, content_type):
        rng = random.Random(hashlib.sha256(frame).digest())
        return EmotionResult(emotion=rng.choice(EMOTIONS), confidence=0.8, mock=True)


class HttpAIClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    async def request(self, path, timeout, **kwargs):
        # Disable redirects: configured AI endpoint must not redirect credentials.
        async with httpx.AsyncClient(
            transport=self.transport,
            base_url=self.settings.ai_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self.settings.ai_api_key}"},
            follow_redirects=False,
            timeout=httpx.Timeout(timeout, connect=5),
        ) as client:
            async with client.stream("POST", path, **kwargs) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > self.settings.max_ai_response_bytes:
                        raise ValueError("AI response exceeds limit")
                    data.extend(chunk)
                return bytes(data)

    async def analyze_video(self, recording_id, url, duration, idempotency_key):
        payload = await self.request(
            "/v1/analyze/video",
            self.settings.ai_timeout_seconds,
            json={"recording_id": recording_id, "video_url": url, "duration": duration},
            headers={"Idempotency-Key": idempotency_key},
        )
        return BatchResult.model_validate_json(payload)

    async def analyze_frame(self, frame, content_type):
        payload = await self.request(
            "/v1/analyze/frame",
            self.settings.frame_timeout_seconds,
            files={"frame": ("frame", frame, content_type)},
        )
        return EmotionResult.model_validate_json(payload)


def build_ai(settings):
    return MockAIClient() if settings.ai_mode == "mock" else HttpAIClient(settings)
