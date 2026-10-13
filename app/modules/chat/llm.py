"""Claude as a fallback question parser (contract v1 D5).

Only the question text and the label list are sent: no video, frames or faces. Claude returns
an intent as JSON (structured outputs); answers are always built from database rows.
"""

import json
import logging

import anthropic
from pydantic import BaseModel, ValidationError

from app.integrations.ai_schema import SEGMENT_EMOTIONS
from app.modules.chat.parser import FIND_EMOTION, GET_EMOTION_BY_TIME, UNKNOWN, Intent

logger = logging.getLogger(__name__)

SYSTEM = (
    "You convert a teacher's question about one classroom video into a query. The video was "
    "analysed into emotion segments measured in seconds from the start of the video.\n"
    "Intents:\n"
    f"- {GET_EMOTION_BY_TIME}: which emotions appear in a time range "
    "(e.g. 'Từ 02:00 đến 03:00 học sinh có cảm xúc gì?').\n"
    f"- {FIND_EMOTION}: when one emotion appears, optionally inside a range "
    "(e.g. 'Khi nào học sinh buồn?').\n"
    f"- {UNKNOWN}: anything else, including questions that need data other than these segments.\n"
    "Convert times to seconds (02:30 = 150). Use -1 for a missing start or end and 'none' for a "
    "missing emotion. Map Vietnamese or English emotion words to exactly one label: "
    + ", ".join(SEGMENT_EMOTIONS)
    + ". Never guess a time or emotion that the question does not state."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [GET_EMOTION_BY_TIME, FIND_EMOTION, UNKNOWN]},
        "start_seconds": {"type": "number"},
        "end_seconds": {"type": "number"},
        "emotion": {"type": "string", "enum": [*SEGMENT_EMOTIONS, "none"]},
    },
    "required": ["intent", "start_seconds", "end_seconds", "emotion"],
    "additionalProperties": False,
}


class LlmIntent(BaseModel):
    intent: str
    start_seconds: float
    end_seconds: float
    emotion: str


class ClaudeIntentParser:
    def __init__(self, settings, client=None):
        self.model = settings.chat_llm_model
        self.client = client or anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.chat_llm_timeout_seconds,
            max_retries=1,
        )

    def parse(self, question):
        """Intent or None when the call fails, is refused or returns an invalid shape."""
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM,
                messages=[{"role": "user", "content": question}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": SCHEMA},
                },
                # Policy declines are re-run on a fallback model chosen by the API.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            logger.warning("Chat LLM request failed (%s)", type(exc).__name__)
            return None
        if response.stop_reason in {"refusal", "max_tokens"}:
            logger.warning("Chat LLM stopped with %s", response.stop_reason)
            return None
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            data = LlmIntent.model_validate(json.loads(text))
        except (ValueError, ValidationError):
            logger.warning("Chat LLM returned an invalid intent")
            return None
        if data.intent not in {GET_EMOTION_BY_TIME, FIND_EMOTION, UNKNOWN}:
            return None
        emotion = data.emotion if data.emotion in SEGMENT_EMOTIONS else None
        if data.intent == FIND_EMOTION and emotion is None:
            return None
        start = data.start_seconds if data.start_seconds >= 0 else None
        end = data.end_seconds if data.end_seconds >= 0 else None
        if data.intent == GET_EMOTION_BY_TIME and start is None and end is None:
            return None
        return Intent(data.intent, start, end, emotion)


def build_intent_parser(settings):
    """None when no API key is configured: the chatbot then uses rules only."""
    if not settings.anthropic_api_key.get_secret_value():
        return None
    return ClaudeIntentParser(settings)
