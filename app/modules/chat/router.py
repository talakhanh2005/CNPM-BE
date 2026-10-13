from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from app.core.dependencies import DB, Teacher
from app.core.schemas import Envelope, ok
from app.modules.chat.service import ChatService
from app.modules.timeline.schema import SegmentEmotion

router = APIRouter(tags=["Emotion chatbot (BE-TU-05)"])


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    recording_id: str | None = Field(default=None, max_length=36)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip()


class ReferenceOut(BaseModel):
    start_seconds: float
    end_seconds: float
    emotion: SegmentEmotion


class ParametersOut(BaseModel):
    start_seconds: float | None
    end_seconds: float | None
    emotion: str | None


class ChatOut(BaseModel):
    answer: str
    intent: Literal["GET_EMOTION_BY_TIME", "FIND_EMOTION", "UNKNOWN"]
    parameters: ParametersOut
    references: list[ReferenceOut]
    data_status: Literal["COMPLETED"]
    recording_id: str
    parser: Literal["rules", "llm"]


@router.post("/meetings/{meeting_id}/chat", response_model=Envelope[ChatOut])
def chat(meeting_id: str, data: ChatIn, request: Request, user: Teacher, db: DB):
    """Answer from the analysed timeline only (contract v1 §5.5).

    Owning teacher, after_session meeting, completed analysis; otherwise 409 with
    ``details[0].data_status``. ``references`` are spans the FE can seek the video to.
    """
    service = ChatService(db, request.app.state.chat_llm)
    return ok(service.ask(meeting_id, user, data.question, data.recording_id))
