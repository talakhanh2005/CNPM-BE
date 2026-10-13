"""Chat answers built only from stored segments (contract v1 §5.5): no invented numbers."""

from app.modules.chat.parser import FIND_EMOTION, GET_EMOTION_BY_TIME, UNKNOWN, parse_question
from app.modules.timeline.service import TimelineService
from app.modules.timeline.stats import clip, summarize

LABELS = {
    "happy": "vui vẻ",
    "neutral": "bình thường",
    "sad": "buồn",
    "angry": "tức giận",
    "surprised": "ngạc nhiên",
    "fearful": "sợ hãi",
    "disgusted": "ghê sợ",
    "no_face": "không thấy khuôn mặt",
    "unknown": "không xác định",
}
MAX_LISTED = 10
HELP = (
    "Mình chưa hiểu câu hỏi. Hãy hỏi theo một trong hai dạng: "
    '"Từ 02:00 đến 03:00 học sinh có cảm xúc gì?" hoặc '
    '"Cảm xúc buồn xuất hiện trong khoảng nào?"'
)


def clock(seconds):
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def amount(seconds):
    return f"{round(seconds, 1):g} giây"


def label(emotion):
    return f"{LABELS.get(emotion, emotion)} ({emotion})"


def reference(segment):
    return {
        "start_seconds": segment["start_seconds"],
        "end_seconds": segment["end_seconds"],
        "emotion": segment["emotion"],
    }


class ChatService:
    def __init__(self, db, llm=None):
        self.db, self.llm, self.timeline = db, llm, TimelineService(db)

    def ask(self, meeting_id, user, question, recording_id=None):
        _, recording = self.timeline.resolve(meeting_id, user, recording_id)
        intent, parser = parse_question(question), "rules"
        if intent.intent == UNKNOWN and self.llm is not None:
            parsed = self.llm.parse(question)
            if parsed is not None:
                intent, parser = parsed, "llm"
        duration = recording.duration
        if intent.anchor == "end":
            intent.start_seconds, intent.end_seconds = (
                max(0.0, duration - intent.end_seconds),
                duration,
            )
        segments = self.timeline.segments(recording)
        if intent.intent == GET_EMOTION_BY_TIME:
            answer, references = self.by_time(intent, segments, duration)
        elif intent.intent == FIND_EMOTION:
            answer, references = self.find(intent, segments, duration)
        else:
            answer, references = HELP, []
        return {
            "answer": answer,
            "intent": intent.intent,
            "parameters": {
                "start_seconds": intent.start_seconds,
                "end_seconds": intent.end_seconds,
                "emotion": intent.emotion,
            },
            "references": references,
            "data_status": "COMPLETED",
            "recording_id": recording.id,
            "parser": parser,
        }

    def window(self, intent, duration):
        start = intent.start_seconds or 0.0
        end = duration if intent.end_seconds is None else intent.end_seconds
        if end < start:
            start, end = end, start
        return start, end

    def by_time(self, intent, segments, duration):
        start, end = self.window(intent, duration)
        if start >= duration:
            return (
                f"Khoảng {clock(start)}–{clock(end)} nằm ngoài video (video dài {clock(duration)}).",
                [],
            )
        end = min(end, duration)
        window = clip(segments, start, end)
        stats = summarize(window, start, end)
        references = [reference(s) for s in window]
        if intent.point:
            at = next((s for s in window), None)
            if at is None:
                return f"Không có dữ liệu tại {clock(start)}.", []
            confidence = at["avg_confidence"]
            detail = f" (độ tin cậy trung bình {confidence:.2f})" if confidence is not None else ""
            return f"Tại {clock(start)}: {label(at['emotion'])}{detail}.", references
        head = f"Từ {clock(start)} đến {clock(end)}"
        if not stats["analyzed_seconds"]:
            answer = f"{head} không có dữ liệu cảm xúc hợp lệ"
        else:
            parts = ", ".join(
                f"{label(emotion)} {amount(share['seconds'])} ({share['percent']:g}%)"
                for emotion, share in stats["emotions"].items()
            )
            answer = (
                f"{head} (đã phân tích {amount(stats['analyzed_seconds'])}"
                f"/{amount(stats['total_seconds'])}): {parts}"
            )
        if stats["no_face_seconds"]:
            answer += f". Không thấy khuôn mặt {amount(stats['no_face_seconds'])}"
        if stats["unknown_seconds"]:
            answer += f". Không xác định {amount(stats['unknown_seconds'])}"
        return answer + ".", references

    def find(self, intent, segments, duration):
        bounded = intent.start_seconds is not None or intent.end_seconds is not None
        start, end = self.window(intent, duration) if bounded else (0.0, duration)
        end = min(end, duration)
        matches = [s for s in clip(segments, start, end) if s["emotion"] == intent.emotion]
        where = f"trong khoảng {clock(start)}–{clock(end)}" if bounded else "trong video"
        if not matches:
            return f"Không ghi nhận cảm xúc {label(intent.emotion)} {where}.", []
        total = sum(s["end_seconds"] - s["start_seconds"] for s in matches)
        spans = ", ".join(
            f"{clock(s['start_seconds'])}–{clock(s['end_seconds'])}" for s in matches[:MAX_LISTED]
        )
        more = f" và {len(matches) - MAX_LISTED} khoảng khác" if len(matches) > MAX_LISTED else ""
        answer = (
            f"Cảm xúc {label(intent.emotion)} xuất hiện {len(matches)} lần {where}, "
            f"tổng {amount(total)}: {spans}{more}."
        )
        return answer, [reference(s) for s in matches]
