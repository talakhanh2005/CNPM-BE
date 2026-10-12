"""Verify the checked-out AI wire schema without loading native/model dependencies."""

import importlib.util
from pathlib import Path

import httpx
import pytest

from app.core.db import now
from app.integrations.ai import HttpAIClient
from app.integrations.ai_schema import EMOTIONS, FrameResult


@pytest.mark.asyncio
async def test_http_client_accepts_sibling_ai_schema(env):
    path = (Path(__file__).resolve().parents[3] / "face-emotion-AI" / "face-emotion-AI"
            / "src" / "openemotion" / "api" / "schema.py")
    if not path.exists():
        pytest.skip("Sibling AI repository is not checked out")
    spec = importlib.util.spec_from_file_location("ai_contract_verification", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.EMOTIONS == EMOTIONS
    stamp = now()
    response = module.FrameResult(
        frame_id="contract-frame", timestamp=stamp, face_detected=True, face_id="face",
        emotion="happy", confidence=0.8,
        probabilities={e: 0.8 if e == "happy" else 0.2 / 6 for e in EMOTIONS},
    )
    payload = response.model_dump(mode="json")
    FrameResult.model_validate(payload)

    def handle(request):
        assert request.url.path == "/v1/analyze/frame"
        assert request.headers["authorization"] == "Bearer contract-ai-key"
        assert "multipart/form-data" in request.headers["content-type"]
        assert b"contract-frame" in request.content and stamp.isoformat().encode() in request.content
        return httpx.Response(200, json=payload)

    env.settings.ai_api_key = "contract-ai-key"
    client = HttpAIClient(env.settings, transport=httpx.MockTransport(handle))
    result = await client.analyze_frame(b"image-bytes", "image/jpeg", "contract-frame", stamp)
    assert result.frame_id == response.frame_id and result.timestamp == stamp
    assert result.probabilities == response.probabilities
