from contextlib import ExitStack
from datetime import timedelta

import pytest
from pydantic import SecretStr

from app.core.db import now
from app.core.security import issue_token
from app.integrations.ai_schema import EMOTIONS, FrameResult
from app.modules.auth.model import User
from app.modules.emotions.service import EmotionService


def prediction(frame_id, stamp, emotion="happy"):
    return FrameResult(frame_id=frame_id, timestamp=stamp, emotion=emotion, confidence=0.8,
                       face_detected=True, face_id="face",
                       probabilities={e: 0.8 if e == emotion else 0.2 / 6 for e in EMOTIONS})


def add_user(env, name, role):
    with env.factory() as db:
        user = User(id=name, email=f"{name}@example.com", full_name=name, role=role,
                    password_hash="unused", created_at=now())
        db.add(user)
        db.commit()
    env.users[name] = user
    env.tokens[name] = issue_token(name, "access", env.settings)
    env.headers[name] = {"Authorization": f"Bearer {env.tokens[name]}"}


def test_one_teacher_three_students_signaling_reconnect(env, room):
    add_user(env, "third", "student")
    for name in ("other", "third"):
        assert env.client.post(f"/meetings/{room}/join", headers=env.headers[name]).status_code == 200
    with ExitStack() as stack:
        sockets = {}
        for name in ("teacher", "student", "other", "third"):
            socket = stack.enter_context(env.client.websocket_connect(f"/ws/meetings/{room}"))
            socket.send_json({"type": "AUTH", "token": env.tokens[name]})
            joined = socket.receive_json()["data"]
            assert len(joined["peers"]) == len(sockets)
            for existing in sockets.values():
                assert existing.receive_json()["data"]["type"] == "JOIN"
            sockets[name] = socket
        sockets["teacher"].send_json({"type": "OFFER", "target_id": "third",
                                      "payload": {"type": "offer", "sdp": "v=0"}})
        assert sockets["third"].receive_json()["data"]["sender_id"] == "teacher"
        sockets["other"].send_json({"type": "LEAVE"})
        for name in ("teacher", "student", "third"):
            assert sockets[name].receive_json()["data"]["sender_id"] == "other"
    assert env.client.post(f"/meetings/{room}/join", headers=env.headers["other"]).status_code == 200


def test_dashboard_filters_weights_empty_and_permissions(env, room):
    env.client.post(f"/meetings/{room}/join", headers=env.headers["other"])
    service = EmotionService(env.factory, env.settings)
    start = now() - timedelta(seconds=10)
    for i, (name, emotion) in enumerate((("student", "happy"), ("student", "sad"), ("other", "happy"))):
        stamp = start + timedelta(seconds=i)
        service.save(room, env.users[name], stamp, prediction(f"sample-{i}", stamp, emotion))
    path = f"/meetings/{room}/dashboard"
    data = env.client.get(path, headers=env.headers["teacher"]).json()["data"]
    assert data["sample_count"] == 3
    assert data["distribution"]["happy"] == pytest.approx(66.6667)
    assert data["positive_negative_ratio"] == 2
    assert len(data["students"]) == 2 and len(data["trend"]) >= 1
    filtered = env.client.get(path, params={"student_id": "student", "end": start.isoformat()},
                              headers=env.headers["teacher"]).json()["data"]
    assert filtered["sample_count"] == 1
    empty = env.client.get(path, params={"student_id": "missing"}, headers=env.headers["teacher"]).json()["data"]
    assert empty["sample_count"] == 0 and empty["average_confidence"] is None
    for name in ("student", "other", "outsider"):
        assert env.client.get(path, headers=env.headers[name]).status_code == 403
    assert env.client.get(path).status_code == 401
    assert env.client.get(path, params={"start": (start + timedelta(days=1)).isoformat(),
                                       "end": start.isoformat()}, headers=env.headers["teacher"]).status_code == 422


def test_internal_ingest_duplicate_aggregate_and_log_crud(env, room):
    env.settings.internal_ai_key = SecretStr("internal-test-key")
    body = {"meeting_id": room, "student_id": "student",
            "result": prediction("callback-1", now()).model_dump(mode="json")}
    key = {"X-AI-Key": "internal-test-key"}
    assert env.client.post("/internal/emotions", json=body).status_code == 401
    with env.client.websocket_connect(f"/ws/meetings/{room}") as teacher:
        teacher.send_json({"type": "AUTH", "token": env.tokens["teacher"]})
        teacher.receive_json()
        response = env.client.post("/internal/emotions", json=body, headers=key)
        assert response.status_code == 200, response.text
        assert teacher.receive_json()["data"]["student_id"] == "student"
        aggregate = teacher.receive_json()["data"]
        assert aggregate["type"] == "EMOTION_AGGREGATE" and aggregate["sample_count"] == 1
    assert env.client.post("/internal/emotions", json=body, headers=key).status_code == 409
    logs = f"/meetings/{room}/emotion-logs"
    data = env.client.get(logs, params={"student_id": "student", "limit": 1}, headers=env.headers["teacher"]).json()["data"]
    assert data["total"] == 1
    sample_path = f"{logs}/{response.json()['data']['sample_id']}"
    assert env.client.patch(sample_path, json={"logged": False}, headers=env.headers["outsider"]).status_code == 403
    assert env.client.patch(sample_path, json={"logged": False}, headers=env.headers["teacher"]).status_code == 200
    assert env.client.get(logs, headers=env.headers["teacher"]).json()["data"]["total"] == 0
    assert env.client.delete(sample_path, headers=env.headers["teacher"]).status_code == 200
    assert env.client.get(f"/meetings/{room}/summary", headers=env.headers["teacher"]).json()["data"]["sample_count"] == 0


def test_admin_cannot_self_register_or_bypass_teacher_ownership(env, room):
    add_user(env, "admin", "admin")
    for path in ("/admin/users", "/admin/meetings"):
        assert env.client.get(path).status_code == 401
        for name in ("teacher", "student"):
            assert env.client.get(path, headers=env.headers[name]).status_code == 403
        response = env.client.get(path, headers=env.headers["admin"])
        assert response.status_code == 200, response.text
        assert "password_hash" not in response.text
    assert env.client.post("/auth/register", json={"email": "hack@example.test", "password": "password123",
                           "full_name": "Hack", "role": "admin"}).status_code == 422
    assert env.client.post(f"/meetings/{room}/join", headers=env.headers["admin"]).status_code == 403
    assert env.client.get(f"/meetings/{room}/dashboard", headers=env.headers["admin"]).status_code == 403


def test_invalid_access_token_and_student_direct_urls(env, room):
    for suffix in ("report", "dashboard", "summary", "emotion-logs"):
        path = f"/meetings/{room}/{suffix}"
        assert env.client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert env.client.get(path, headers=env.headers["student"]).status_code == 403
