"""Rule-based intent parser for timeline questions (contract v1 §5.5).

Understands mm:ss, hh:mm:ss, "X phút Y giây", "X giây", "phút X", "2 phút đầu/cuối" and maps
Vietnamese/English emotion words to labels. Ambiguous short words are matched only with
diacritics ("sợ", "giận"), so "thời gian" or "số" never become emotions.
"""

import re
import unicodedata
from dataclasses import dataclass

GET_EMOTION_BY_TIME = "GET_EMOTION_BY_TIME"
FIND_EMOTION = "FIND_EMOTION"
UNKNOWN = "UNKNOWN"

# Matched against the lower-cased question with diacritics.
ACCENTED = {
    "vui": "happy",
    "vui vẻ": "happy",
    "vui mừng": "happy",
    "hạnh phúc": "happy",
    "cười": "happy",
    "buồn": "sad",
    "buồn bã": "sad",
    "giận": "angry",
    "tức giận": "angry",
    "giận dữ": "angry",
    "cáu": "angry",
    "bực": "angry",
    "bực bội": "angry",
    "ngạc nhiên": "surprised",
    "bất ngờ": "surprised",
    "sợ": "fearful",
    "sợ hãi": "fearful",
    "lo sợ": "fearful",
    "hoảng sợ": "fearful",
    "ghê tởm": "disgusted",
    "kinh tởm": "disgusted",
    "chán ghét": "disgusted",
    "bình thường": "neutral",
    "trung tính": "neutral",
    "bình thản": "neutral",
    "không thấy mặt": "no_face",
    "không thấy khuôn mặt": "no_face",
    "không có mặt": "no_face",
    "không xác định": "unknown",
}
# Matched against the question without diacritics: only unambiguous phrases.
ASCII = {
    "vui": "happy",
    "vui ve": "happy",
    "vui mung": "happy",
    "hanh phuc": "happy",
    "happy": "happy",
    "happiness": "happy",
    "buon": "sad",
    "buon ba": "sad",
    "sad": "sad",
    "sadness": "sad",
    "tuc gian": "angry",
    "gian du": "angry",
    "angry": "angry",
    "anger": "angry",
    "ngac nhien": "surprised",
    "bat ngo": "surprised",
    "surprised": "surprised",
    "surprise": "surprised",
    "so hai": "fearful",
    "lo so": "fearful",
    "hoang so": "fearful",
    "fear": "fearful",
    "fearful": "fearful",
    "scared": "fearful",
    "ghe tom": "disgusted",
    "kinh tom": "disgusted",
    "disgust": "disgusted",
    "disgusted": "disgusted",
    "binh thuong": "neutral",
    "trung tinh": "neutral",
    "neutral": "neutral",
    "khong thay mat": "no_face",
    "khong thay khuon mat": "no_face",
    "khong co mat": "no_face",
    "no face": "no_face",
    "no_face": "no_face",
    "khong xac dinh": "unknown",
    "unknown": "unknown",
}

CLOCK = re.compile(r"(?<![\d:])(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?(?![\d:])")
MINUTES = re.compile(
    r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:phut|minutes?|mins?)\b(?:\s*(\d+)\s*(?:giay|seconds?|secs?|s)\b)?"
)
MINUTE_PREFIX = re.compile(r"\bphut\s*(?:thu\s*)?(\d+)\b")
SECONDS = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:giay|seconds?|secs?|s)\b")
FROM_START = re.compile(r"\b(?:dau|dau tien|first)\b")
FROM_END = re.compile(r"\b(?:cuoi|cuoi cung|last)\b")


@dataclass
class Intent:
    intent: str
    start_seconds: float | None = None
    end_seconds: float | None = None
    emotion: str | None = None
    # "start"/"end": a single duration counted from the start or the end of the video.
    anchor: str | None = None
    point: bool = False


def strip_accents(text):
    text = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _number(value):
    return float(value.replace(",", "."))


def find_times(ascii_text):
    """[(position, seconds)] in reading order; overlapping matches are ignored."""
    found, taken = [], []

    def free(span):
        return all(span[1] <= a or span[0] >= b for a, b in taken)

    for match in CLOCK.finditer(ascii_text):
        a, b, c = match.groups()
        seconds = int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)
        found.append((match.start(), float(seconds)))
        taken.append(match.span())
    for match in MINUTES.finditer(ascii_text):
        if free(match.span()):
            seconds = _number(match.group(1)) * 60 + (int(match.group(2)) if match.group(2) else 0)
            found.append((match.start(), seconds))
            taken.append(match.span())
    for match in MINUTE_PREFIX.finditer(ascii_text):
        if free(match.span()):
            found.append((match.start(), float(int(match.group(1)) * 60)))
            taken.append(match.span())
    for match in SECONDS.finditer(ascii_text):
        if free(match.span()):
            found.append((match.start(), _number(match.group(1))))
            taken.append(match.span())
    return [seconds for _, seconds in sorted(found)]


def find_emotion(text, ascii_text):
    """First emotion mentioned; longer phrases win at the same position."""
    # "vui lòng" means "please", not "happy".
    text = re.sub(r"vui lòng", "        ", text)
    ascii_text = re.sub(r"vui long", "        ", ascii_text)
    candidates = []
    for table, haystack in ((ACCENTED, text), (ASCII, ascii_text)):
        for phrase, label in table.items():
            for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", haystack):
                candidates.append((match.start(), -len(phrase), label))
    return min(candidates)[2] if candidates else None


def parse_question(question):
    text = unicodedata.normalize("NFC", question).lower().strip()
    ascii_text = strip_accents(text)
    times = find_times(ascii_text)
    emotion = find_emotion(text, ascii_text)
    intent = Intent(FIND_EMOTION if emotion else GET_EMOTION_BY_TIME if times else UNKNOWN)
    intent.emotion = emotion
    if len(times) >= 2:
        intent.start_seconds, intent.end_seconds = times[0], times[1]
    elif len(times) == 1:
        if FROM_END.search(ascii_text):
            intent.anchor, intent.end_seconds = "end", times[0]
        elif FROM_START.search(ascii_text):
            intent.start_seconds, intent.end_seconds = 0.0, times[0]
        else:
            # "lúc 01:30": the emotion at that moment.
            intent.start_seconds, intent.end_seconds, intent.point = times[0], times[0] + 1, True
    return intent
