from hmac import compare_digest

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.core.db import now
from app.core.errors import AppError
from app.core.schemas import Envelope, ok
from app.integrations.ai_schema import FrameResult
from app.modules.auth.model import User
from app.modules.emotions.analytics import realtime_summary
from app.modules.emotions.service import EmotionService

router = APIRouter(tags=["Internal AI ingest"])


class IngestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meeting_id: str = Field(min_length=1, max_length=36)
    student_id: str = Field(min_length=1, max_length=36)
    result: FrameResult


class IngestOut(BaseModel):
    sample_id: str
    logged: bool


@router.post("/internal/emotions", response_model=Envelope[IngestOut])
async def ingest(data: IngestIn, request: Request):
    """Trusted AI callback. X-AI-Key is required and independent of user JWTs."""
    state = request.app.state
    expected = state.settings.internal_ai_key.get_secret_value()
    if not expected or not compare_digest(
        request.headers.get("x-ai-key", "").encode(), expected.encode()
    ):
        raise AppError(401, "INVALID_AI_KEY", "Valid internal AI key required")

    def persist():
        with state.session_factory() as db:
            user = db.get(User, data.student_id)
            if user is None:
                raise AppError(404, "USER_NOT_FOUND", "Student not found")
        service = EmotionService(state.session_factory, state.settings)
        service.authorize(data.meeting_id, user)
        return service.save(data.meeting_id, user, now(), data.result)

    sample_id, logged = await run_in_threadpool(persist)
    await state.manager.broadcast(
        data.meeting_id,
        {
            "type": "EMOTION",
            "sample_id": sample_id,
            "meeting_id": data.meeting_id,
            "student_id": data.student_id,
            "logged": logged,
            **data.result.model_dump(mode="json"),
        },
        role="teacher",
    )
    aggregate = await run_in_threadpool(
        realtime_summary,
        state.session_factory,
        data.meeting_id,
        state.settings.emotion_aggregation_window_seconds,
    )
    await state.manager.broadcast(data.meeting_id, aggregate, role="teacher")
    return ok({"sample_id": sample_id, "logged": logged})
