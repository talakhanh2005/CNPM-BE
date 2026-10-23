"""Gemini function calling as a fallback question parser (contract v1 D5).

Only the question text and tool declarations are sent: no video, frames, faces or stored emotion
data. Gemini selects one of the backend's existing timeline functions; answers are still built
deterministically from database rows. The API key travels in the ``x-goog-api-key`` header,
never in the URL, and is never logged.
"""

import json
import logging
import time

import httpx

from app.integrations.ai_schema import SEGMENT_EMOTIONS
from app.modules.chat.parser import FIND_EMOTION, GET_EMOTION_BY_TIME, UNKNOWN, Intent

logger = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
RETRY_STATUSES = {429, 500, 503}

GET_BY_TIME_TOOL = "get_emotions_by_time"
FIND_EMOTION_TOOL = "find_emotion_occurrences"
UNSUPPORTED_TOOL = "unsupported_question"

SYSTEM = (
    "You route a teacher's Vietnamese or English question about an analysed classroom video to "
    "exactly one available function. Times are seconds from the start of the video. Convert "
    "timestamps such as 02:30 to 150 seconds. Use -1 when the teacher did not specify a boundary. "
    "Use get_emotions_by_time with both boundaries -1 for a whole-video overview or dominant "
    "emotion question. Map emotion wording to exactly one allowed label. Never invent a time, "
    "emotion, student identity or fact. Use unsupported_question when the available functions "
    "cannot answer from emotion timeline data."
)

TIME_PROPERTIES = {
    "start_seconds": {
        "type": "number",
        "description": "Inclusive start in seconds, or -1 when the question has no start.",
    },
    "end_seconds": {
        "type": "number",
        "description": "Exclusive end in seconds, or -1 when the question has no end.",
    },
}

FUNCTION_DECLARATIONS = [
    {
        "name": GET_BY_TIME_TOOL,
        "description": (
            "Summarize emotions in a time range, at a timestamp, or across the whole video. "
            "Use for overview, dominant emotion, distribution and time-range questions."
        ),
        "parameters": {
            "type": "object",
            "properties": TIME_PROPERTIES,
            "required": ["start_seconds", "end_seconds"],
        },
    },
    {
        "name": FIND_EMOTION_TOOL,
        "description": "Find every timeline interval where a requested emotion appears.",
        "parameters": {
            "type": "object",
            "properties": {
                "emotion": {
                    "type": "string",
                    "enum": list(SEGMENT_EMOTIONS),
                    "description": "Canonical emotion label requested by the teacher.",
                },
                **TIME_PROPERTIES,
            },
            "required": ["emotion", "start_seconds", "end_seconds"],
        },
    },
    {
        "name": UNSUPPORTED_TOOL,
        "description": "Use when neither timeline function can answer the question safely.",
        "parameters": {"type": "object", "properties": {}},
    },
]

OPENAI_TOOLS = [
    {
        "type": "function",
        "name": declaration["name"],
        "description": declaration["description"],
        "parameters": {**declaration["parameters"], "additionalProperties": False},
        "strict": True,
    }
    for declaration in FUNCTION_DECLARATIONS
]


def intent_from_call(name, args):
    if name == UNSUPPORTED_TOOL:
        return Intent(UNKNOWN)

    def boundary(key):
        value = args.get(key, -1)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError
        return float(value) if value >= 0 else None

    try:
        start, end = boundary("start_seconds"), boundary("end_seconds")
    except ValueError:
        logger.warning("Chat LLM returned invalid function arguments")
        return None
    if name == GET_BY_TIME_TOOL:
        return Intent(GET_EMOTION_BY_TIME, start, end)
    if name == FIND_EMOTION_TOOL:
        emotion = args.get("emotion")
        if emotion not in SEGMENT_EMOTIONS:
            return None
        return Intent(FIND_EMOTION, start, end, emotion)
    return None


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
            "tools": [{"functionDeclarations": FUNCTION_DECLARATIONS}],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": [
                        GET_BY_TIME_TOOL,
                        FIND_EMOTION_TOOL,
                        UNSUPPORTED_TOOL,
                    ],
                }
            },
            "generationConfig": {"temperature": 0},
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
        """Intent or None when the call fails, is blocked or returns invalid arguments."""
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
        call = next((part.get("functionCall") for part in parts if part.get("functionCall")), None)
        if not call:
            logger.warning("Chat LLM returned no function call")
            return None
        return intent_from_call(call.get("name"), call.get("args") or {})


class OpenAIIntentParser:
    """Use the OpenAI Responses API to select one deterministic timeline function."""

    def __init__(self, settings, client=None):
        self.model = settings.openai_chat_model
        self.key = settings.openai_api_key.get_secret_value()
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(settings.chat_llm_timeout_seconds, connect=5)
        )

    def _request(self, question):
        body = {
            "model": self.model,
            "instructions": SYSTEM,
            "input": question,
            "tools": OPENAI_TOOLS,
            "tool_choice": "required",
            "parallel_tool_calls": False,
        }
        for attempt in range(2):
            try:
                response = self.client.post(
                    OPENAI_RESPONSES_URL,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self.key}",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                logger.warning("OpenAI chat request failed (%s)", type(exc).__name__)
                return None
            if response.status_code in RETRY_STATUSES and attempt == 0:
                time.sleep(0.6)
                continue
            if response.status_code != 200:
                logger.warning("OpenAI chat request failed (HTTP %s)", response.status_code)
                return None
            try:
                return response.json()
            except ValueError:
                return None
        return None

    def parse(self, question):
        data = self._request(question)
        if not data:
            return None
        call = next(
            (item for item in data.get("output", []) if item.get("type") == "function_call"),
            None,
        )
        if not call:
            logger.warning("OpenAI chat returned no function call")
            return None
        try:
            args = json.loads(call.get("arguments") or "{}")
        except (TypeError, ValueError):
            logger.warning("OpenAI chat returned invalid function arguments")
            return None
        return intent_from_call(call.get("name"), args)


def build_intent_parser(settings):
    """Select the configured provider; no key means the chatbot safely uses rules only."""
    provider = settings.chat_llm_provider
    if provider in {"openai", "auto"} and settings.openai_api_key.get_secret_value():
        return OpenAIIntentParser(settings)
    if provider in {"gemini", "auto"} and settings.gemini_api_key.get_secret_value():
        return GeminiIntentParser(settings)
    return None
