"""BE-TU tasks: realtime infer, segments/timeline, chatbot, request id (contract v1)."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fakes import FakeAIClient
from pydantic import ValidationError

from app.integrations.ai_schema import BatchResult, Segment, TimelinePoint
from app.modules.analysis.service import process_one
from app.modules.chat.llm import GeminiIntentParser
from app.modules.chat.parser import (
    FIND_EMOTION,
    GET_EMOTION_BY_TIME,
    UNKNOWN,
    Intent,
    parse_question,
)
from app.modules.recordings.repository import RecordingRepository
from app.modules.timeline.repository import TimelineRepository
from app.modules.timeline.segments import build_segments
from app.modules.timeline.service import ingest
from app.modules.timeline.stats import summarize

VIDEO = b"\x00\x00\x00\x20ftypisom"  # the test storage reports 30 seconds
SEGMENTS = [
    {"start_seconds": 0, "end_seconds": 10, "emotion": "neutral", "avg_confidence": 0.87},
    {"start_seconds": 10, "end_seconds": 18, "emotion": "happy", "avg_confidence": 0.91},
    {"start_seconds": 18, "end_seconds": 22, "emotion": "no_face", "avg_confidence": None},
    {"start_seconds": 22, "end_seconds": 30, "emotion": "sad", "avg_confidence": 0.7},
]


class SegmentAI(FakeAIClient):
    """AI build that already returns smoothed segments (contract v1 §6.2)."""

    async def analyze_video(self, recording_id, url, duration, idempotency_key):
        return BatchResult(
            sample_counts={"neutral": 10, "happy": 8, "sad": 8},
            timeline=[],
            summary="26 classified samples.",
            segments=SEGMENTS,
            model_version="emotion-v1",
        )


def points(*items):
    return [TimelinePoint(timestamp=t, emotion=e, confidence=c) for t, e, c in items]


def result_with(timeline):
    counts = {}
    for point in timeline:
        counts[point.emotion] = counts.get(point.emotion, 0) + 1
    return BatchResult(sample_counts=counts, timeline=timeline)


def recorded_meeting(env, ai=None, process=True):
    teacher = env.headers["teacher"]
    room = env.client.post("/meetings", json={"mode": "after_session"}, headers=teacher).json()[
        "data"
    ]["id"]
    env.client.post(f"/meetings/{room}/join", headers=env.headers["student"])
    response = env.client.post(
        f"/meetings/{room}/recordings",
        content=VIDEO,
        headers={**teacher, "Content-Type": "video/mp4"},
    )
    assert response.status_code == 201, response.text
    if ai is not None:
        env.app.state.ai = ai
    if process:
        assert asyncio.run(
            process_one(env.factory, env.app.state.ai, env.app.state.storage, env.settings)
        )
    return room, response.json()["data"]["id"]


def ask(env, room, question, name="teacher"):
    return env.client.post(
        f"/meetings/{room}/chat", json={"question": question}, headers=env.headers[name]
    )


# ------------------------------------------------------------------ segments (unit)


def test_t04_ten_neutral_frames_become_one_segment():
    timeline = points(*[(float(t), "neutral", 0.8) for t in range(10)])
    segments, source = build_segments(result_with(timeline), 300)
    assert source == "derived"
    assert [(s["start_seconds"], s["end_seconds"], s["emotion"]) for s in segments] == [
        (0, 10, "neutral"),
        (10, 300, "no_face"),
    ]
    assert segments[0]["avg_confidence"] == 0.8 and segments[0]["sample_count"] == 10


def test_t05_missing_face_becomes_no_face_never_neutral():
    timeline = points(
        *[(float(t), "neutral", 0.9) for t in range(5)],
        *[(float(t), "happy", 0.6) for t in range(10, 13)],
    )
    segments, _ = build_segments(result_with(timeline), 13)
    assert [(s["start_seconds"], s["end_seconds"], s["emotion"]) for s in segments] == [
        (0, 5, "neutral"),
        (5, 10, "no_face"),
        (10, 13, "happy"),
    ]
    empty, _ = build_segments(BatchResult(sample_counts={}, timeline=[]), 42)
    assert [(s["start_seconds"], s["end_seconds"], s["emotion"]) for s in empty] == [
        (0, 42, "no_face")
    ]


def test_majority_label_when_several_faces_share_a_timestamp():
    timeline = points((0.0, "sad", 0.9), (0.0, "happy", 0.6), (0.0, "happy", 0.7))
    segments, _ = build_segments(result_with(timeline), 1)
    assert segments[0]["emotion"] == "happy" and segments[0]["avg_confidence"] == 0.65


def test_low_confidence_becomes_unknown_never_neutral():
    timeline = points(
        *[(float(t), "neutral", 0.9) for t in range(3)],
        *[(float(t), "neutral", 0.2) for t in range(3, 6)],
        *[(float(t), "happy", 0.39) for t in range(6, 8)],
        (8.0, "sad", 0.4),
    )
    segments, _ = build_segments(result_with(timeline), 9)
    assert [(s["start_seconds"], s["end_seconds"], s["emotion"]) for s in segments] == [
        (0, 3, "neutral"),
        (3, 8, "unknown"),  # 0.2 and 0.39 merge; the label is not kept
        (8, 9, "sad"),  # exactly the threshold is still a valid prediction
    ]
    stats = summarize(segments, 0, 9)
    assert stats["unknown_seconds"] == 5 and stats["analyzed_seconds"] == 4
    assert stats["emotions"]["neutral"]["seconds"] == 3
    assert stats["coverage"] == round(4 / 9, 4)
    strict, _ = build_segments(result_with(timeline), 9, low_confidence=0.0)
    assert "unknown" not in {s["emotion"] for s in strict}


def test_ai_segments_are_validated_merged_and_clamped():
    with pytest.raises(ValidationError):
        BatchResult(sample_counts={}, segments=[SEGMENTS[1], SEGMENTS[0]])
    with pytest.raises(ValidationError):
        Segment(start_seconds=0, end_seconds=1, emotion="no_face", avg_confidence=0.5)
    with pytest.raises(ValidationError):
        Segment(start_seconds=3, end_seconds=3, emotion="sad")
    result = BatchResult(
        sample_counts={},
        segments=[
            {"start_seconds": 0, "end_seconds": 4, "emotion": "sad", "avg_confidence": 0.5},
            {"start_seconds": 4, "end_seconds": 10.3, "emotion": "sad", "avg_confidence": 1.0},
        ],
    )
    segments, source = build_segments(result, 10)
    assert source == "ai"
    assert [(s["start_seconds"], s["end_seconds"]) for s in segments] == [(0, 10)]
    assert segments[0]["avg_confidence"] == 0.8


def test_summary_counts_only_analysed_time():
    stats = summarize([{**s} for s in SEGMENTS], 0, 30)
    assert stats["analyzed_seconds"] == 26 and stats["no_face_seconds"] == 4
    assert stats["coverage"] == round(26 / 30, 4)
    assert stats["emotions"]["neutral"] == {"seconds": 10, "percent": 38.46}
    assert stats["dominant_emotion"] == "neutral"
    assert summarize([], 0, 10)["dominant_emotion"] is None


# ------------------------------------------------------------------ timeline API


def test_timeline_from_ai_segments(env):
    room, recording = recorded_meeting(env, SegmentAI())
    path = f"/meetings/{room}/emotions/timeline"
    data = env.client.get(path, headers=env.headers["teacher"]).json()["data"]
    assert data["recording_id"] == recording and data["data_status"] == "COMPLETED"
    assert data["segments_source"] == "ai" and data["model_version"] == "emotion-v1"
    assert [s["emotion"] for s in data["segments"]] == ["neutral", "happy", "no_face", "sad"]
    assert data["summary"]["dominant_emotion"] == "neutral"

    ranged = env.client.get(f"{path}?from_seconds=5&to_seconds=15", headers=env.headers["teacher"])
    window = ranged.json()["data"]
    assert [(s["start_seconds"], s["end_seconds"]) for s in window["segments"]] == [
        (5, 10),
        (10, 15),
    ]
    assert window["summary"]["emotions"]["happy"]["percent"] == 50
    bad = env.client.get(f"{path}?from_seconds=15&to_seconds=5", headers=env.headers["teacher"])
    assert bad.status_code == 422


def test_timeline_access_and_status_rules(env, room):
    teacher = env.headers["teacher"]
    # T02/T06 side for Tú's endpoints: realtime meetings have no timeline or chat.
    response = env.client.get(f"/meetings/{room}/emotions/timeline", headers=teacher)
    assert response.status_code == 409
    assert response.json()["data"]["code"] == "INVALID_MEETING_MODE"
    assert ask(env, room, "Khi nào học sinh buồn?").json()["data"]["code"] == "INVALID_MEETING_MODE"

    empty = env.client.post("/meetings", json={"mode": "after_session"}, headers=teacher).json()[
        "data"
    ]["id"]
    response = env.client.get(f"/meetings/{empty}/emotions/timeline", headers=teacher)
    assert response.json()["data"]["details"] == [{"data_status": "NO_RECORDING"}]

    queued, _ = recorded_meeting(env, process=False)
    response = env.client.get(f"/meetings/{queued}/emotions/timeline", headers=teacher)
    assert response.status_code == 409
    assert response.json()["data"]["details"] == [{"data_status": "QUEUED"}]
    assert ask(env, queued, "Khi nào học sinh buồn?").status_code == 409

    done, _ = recorded_meeting(env, SegmentAI())
    path = f"/meetings/{done}/emotions/timeline"
    # T10: students and other teachers are refused.
    assert env.client.get(path, headers=env.headers["student"]).status_code == 403
    assert env.client.get(path, headers=env.headers["outsider"]).status_code == 403
    assert ask(env, done, "Khi nào học sinh buồn?", "student").status_code == 403
    unknown = env.client.get(f"{path}?recording_id=nope", headers=teacher)
    assert unknown.status_code == 404


def test_t11_ingestion_is_idempotent_and_lazy(env):
    room, recording_id = recorded_meeting(env)  # mock AI: points only, segments derived
    with env.factory() as db:
        recording = RecordingRepository(db).get(recording_id)
        first = TimelineRepository(db).segments(recording_id)
        ingest(db, recording)
        ingest(db, recording)
        assert TimelineRepository(db).segments(recording_id) == first
        TimelineRepository(db).replace(recording, None, [], None, "derived")
    data = env.client.get(
        f"/meetings/{room}/emotions/timeline", headers=env.headers["teacher"]
    ).json()["data"]
    # Rebuilt on read from the stored AI result.
    assert data["segments_source"] == "derived" and data["model_version"] == "mock"
    assert data["segments"][-1]["end_seconds"] == 30


def test_t11_repeated_analysis_requests_keep_one_job_and_one_segment_set(env):
    room, recording_id = recorded_meeting(env)
    teacher = env.headers["teacher"]
    status = f"/recordings/{recording_id}/status"
    job_id = env.client.get(status, headers=teacher).json()["data"]["job_id"]
    with env.factory() as db:
        before = TimelineRepository(db).segments(recording_id)
    for _ in range(2):  # a retry after completion must not queue or re-ingest anything
        response = env.client.post(f"/recordings/{recording_id}/analyze", headers=teacher)
        assert response.status_code in {200, 202, 409}, response.text
    # Nothing is left to process, so a second worker pass does no work.
    assert not asyncio.run(
        process_one(env.factory, env.app.state.ai, env.app.state.storage, env.settings)
    )
    data = env.client.get(status, headers=teacher).json()["data"]
    assert data["job_id"] == job_id and data["status"] == "completed"
    with env.factory() as db:
        assert TimelineRepository(db).segments(recording_id) == before


# ------------------------------------------------------------------ chatbot


@pytest.mark.parametrize(
    "question, intent, start, end, emotion",
    [
        ("Từ 02:00 đến 03:00 học sinh có cảm xúc gì?", GET_EMOTION_BY_TIME, 120, 180, None),
        ("từ phút 2 đến phút 3 thế nào", GET_EMOTION_BY_TIME, 120, 180, None),
        ("Từ 1 phút 30 giây đến 2 phút?", GET_EMOTION_BY_TIME, 90, 120, None),
        ("2 phút đầu học sinh thế nào?", GET_EMOTION_BY_TIME, 0, 120, None),
        ("Cảm xúc buồn xuất hiện trong khoảng nào?", FIND_EMOTION, None, None, "sad"),
        ("khi nao hoc sinh buon?", FIND_EMOTION, None, None, "sad"),
        ("Từ 1:00 đến 3:00 có lúc nào tức giận không?", FIND_EMOTION, 60, 180, "angry"),
        ("Học sinh có sợ không?", FIND_EMOTION, None, None, "fearful"),
        ("Thời gian học bao lâu?", UNKNOWN, None, None, None),
        ("Vui lòng cho biết số học sinh", UNKNOWN, None, None, None),
    ],
)
def test_rule_parser(question, intent, start, end, emotion):
    parsed = parse_question(question)
    assert (parsed.intent, parsed.start_seconds, parsed.end_seconds, parsed.emotion) == (
        intent,
        start,
        end,
        emotion,
    )


def test_t08_t09_chat_answers_from_stored_segments(env):
    room, recording = recorded_meeting(env, SegmentAI())
    data = ask(env, room, "Từ 00:05 đến 00:15 học sinh có cảm xúc gì?").json()["data"]
    assert data["intent"] == GET_EMOTION_BY_TIME and data["parser"] == "rules"
    assert data["references"] == [
        {"start_seconds": 5, "end_seconds": 10, "emotion": "neutral"},
        {"start_seconds": 10, "end_seconds": 15, "emotion": "happy"},
    ]
    assert "50%" in data["answer"] and data["recording_id"] == recording

    data = ask(env, room, "Cảm xúc buồn xuất hiện khi nào?").json()["data"]
    assert data["intent"] == FIND_EMOTION
    assert data["references"] == [{"start_seconds": 22, "end_seconds": 30, "emotion": "sad"}]
    assert "00:22–00:30" in data["answer"]

    data = ask(env, room, "Khi nào học sinh tức giận?").json()["data"]
    assert data["references"] == [] and "Không ghi nhận" in data["answer"]

    data = ask(env, room, "Từ 00:18 đến 00:22 thế nào?").json()["data"]
    assert "không có dữ liệu cảm xúc hợp lệ" in data["answer"]
    assert "Không thấy khuôn mặt 4 giây" in data["answer"]

    data = ask(env, room, "Lúc 00:12 học sinh thế nào?").json()["data"]
    assert data["answer"].startswith("Tại 00:12: vui vẻ (happy)")

    data = ask(env, room, "2 giây cuối học sinh thế nào?").json()["data"]
    assert data["references"] == [{"start_seconds": 28, "end_seconds": 30, "emotion": "sad"}]

    data = ask(env, room, "Từ 05:00 đến 06:00 có gì?").json()["data"]
    assert "nằm ngoài video" in data["answer"] and data["references"] == []

    data = ask(env, room, "Thời gian học bao lâu?").json()["data"]
    assert data["intent"] == UNKNOWN and data["references"] == []
    assert ask(env, room, "   ").status_code == 422


def test_chat_uses_llm_only_when_rules_fail(env):
    room, _ = recorded_meeting(env, SegmentAI())
    calls = []

    class FakeLLM:
        def parse(self, question):
            calls.append(question)
            return Intent(FIND_EMOTION, emotion="happy")

    env.app.state.chat_llm = FakeLLM()
    data = ask(env, room, "Học sinh có hào hứng không?").json()["data"]
    assert data["parser"] == "llm" and data["intent"] == FIND_EMOTION
    assert data["references"] == [{"start_seconds": 10, "end_seconds": 18, "emotion": "happy"}]
    ask(env, room, "Khi nào học sinh buồn?")
    assert calls == ["Học sinh có hào hứng không?"]


def test_gemini_parser_validates_output():
    sent = []

    def gemini_reply(payload, finish="STOP", status=200):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        body = {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": text}]}}]}
        return httpx.Response(status, json=body)

    good = {"intent": "FIND_EMOTION", "start_seconds": -1, "end_seconds": -1, "emotion": "happy"}
    ranged = {
        "intent": "GET_EMOTION_BY_TIME",
        "start_seconds": 60,
        "end_seconds": 120,
        "emotion": "none",
    }
    replies = [
        gemini_reply(good),
        gemini_reply(good, finish="SAFETY"),
        gemini_reply("not json"),
        gemini_reply({**good, "emotion": "none"}),
        gemini_reply(ranged),
        httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
        httpx.Response(401, json={"error": {"message": "bad key"}}),
        httpx.Response(503, json={}),  # transient overload: retried once...
        gemini_reply(good),  # ...and the retry succeeds
    ]

    def handler(request):
        sent.append(request)
        return replies.pop(0)

    settings = SimpleNamespace(
        chat_llm_model="gemini-3.5-flash",
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
        chat_llm_timeout_seconds=5,
    )
    parser = GeminiIntentParser(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    first = parser.parse("q")
    assert (first.intent, first.emotion, first.start_seconds) == (FIND_EMOTION, "happy", None)
    request = sent[0]
    assert request.url.path.endswith("/models/gemini-3.5-flash:generateContent")
    assert request.headers["x-goog-api-key"] == "test-key" and "test-key" not in str(request.url)
    body = json.loads(request.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["contents"][0]["parts"][0]["text"] == "q"  # only the question is sent
    assert parser.parse("q") is None  # stopped by a safety filter
    assert parser.parse("q") is None  # invalid JSON
    assert parser.parse("q") is None  # FIND_EMOTION without an emotion
    parsed = parser.parse("q")
    assert (parsed.start_seconds, parsed.end_seconds, parsed.emotion) == (60, 120, None)
    assert parser.parse("q") is None  # prompt blocked
    assert parser.parse("q") is None  # HTTP 401: no retry
    assert parser.parse("q").emotion == "happy"  # 503 then success
    assert not replies


# ------------------------------------------------------------------ realtime + request id


def test_infer_route_logs_model_version(env, room, frame_data):
    response = env.client.post(
        f"/meetings/{room}/emotions/infer", json=frame_data, headers=env.headers["student"]
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["model_version"] == "mock"
    logs = env.client.get(f"/meetings/{room}/emotion-logs", headers=env.headers["teacher"])
    assert logs.json()["data"]["items"][0]["model_version"] == "mock"


def test_request_id_header_and_error_envelope(env):
    response = env.client.get("/health", headers={"X-Request-ID": "fe-123"})
    assert response.headers["x-request-id"] == "fe-123"
    generated = env.client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert generated.headers["x-request-id"] != "bad id with spaces"
    error = env.client.get(
        "/meetings/missing", headers={**env.headers["teacher"], "X-Request-ID": "trace-9"}
    )
    assert error.status_code == 404
    assert error.json()["data"]["request_id"] == "trace-9"
