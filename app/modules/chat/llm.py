"""Gemini as a fallback question parser (contract v1 D5).

Only the question text and the label list are sent: no video, frames or faces. Gemini returns
an intent as JSON (response schema); answers are always built from database rows. The API key
travels in the ``x-goog-api-key`` header, never in the URL, and is never logged.
"""

import json
import logging
import time

import httpx
from pydantic import BaseModel, ValidationError

from app.integrations.ai_schema import SEGMENT_EMOTIONS
from app.modules.chat.parser import FIND_EMOTION, GET_EMOTION_BY_TIME, UNKNOWN, Intent

logger = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
RETRY_STATUSES = {429, 500, 503}

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

# Gemini's response schema is an OpenAPI subset (upper-case type names).
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "intent": {"type": "STRING", "enum": [GET_EMOTION_BY_TIME, FIND_EMOTION, UNKNOWN]},
        "start_seconds": {"type": "NUMBER"},
        "end_seconds": {"type": "NUMBER"},
        "emotion": {"type": "STRING", "enum": [*SEGMENT_EMOTIONS, "none"]},
    },
    "required": ["intent", "start_seconds", "end_seconds", "emotion"],
}


class LlmIntent(BaseModel):
    intent: str
    start_seconds: float
    end_seconds: float
    emotion: str


class GeminiIntentParser:
    def __init__(self, settings, client=None):
        self.model = settings.chat_llm_model
        self.key = settings.gemini_api_key.get_secret_value()
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(settings.chat_llm_timeout_seconds, connect=5)
        )

    def _request(self, question):
        """The response JSON, or None after one retry on a transient overload."""
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": question}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": SCHEMA,
            },
        }
        for attempt in range(2):
            try:
                response = self.client.post(
                    f"{API_ROOT}/{self.model}:generateContent",
                    json=body,
                    headers={"x-goog-api-key": self.key},
                )
            except httpx.HTTPError as exc:
                logger.warning("Chat LLM request failed (%s)", type(exc).__name__)
                return None
            if response.status_code in RETRY_STATUSES and attempt == 0:
                time.sleep(0.6)
                continue
            if response.status_code != 200:
                logger.warning("Chat LLM request failed (HTTP %s)", response.status_code)
                return None
            try:
                return response.json()
            except ValueError:
                return None
        return None

    def parse(self, question):
        """Intent or None when the call fails, is blocked or returns an invalid shape."""
        data = self._request(question)
        if not data:
            return None
        candidates = data.get("candidates") or []
        if not candidates or data.get("promptFeedback", {}).get("blockReason"):
            logger.warning("Chat LLM returned no usable candidate")
            return None
        if candidates[0].get("finishReason") not in {None, "STOP"}:
            logger.warning("Chat LLM stopped with %s", candidates[0].get("finishReason"))
            return None
        parts = candidates[0].get("content", {}).get("parts") or []
        text = next((part["text"] for part in parts if "text" in part), "")
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
    if not settings.gemini_api_key.get_secret_value():
        return None
    return GeminiIntentParser(settings)
