from datetime import timedelta
from types import SimpleNamespace

import jwt
import pytest
from test_backend_tasks import prediction

from app.core.db import now
from app.core.security import issue_token
from app.integrations.ai_schema import EMOTIONS
from app.modules.emotions.analytics import summarize
from app.modules.emotions.service import EmotionService


def test_all_seven_classes_and_no_face_ratio():
    samples = [
        SimpleNamespace(
            emotion=e,
            face_detected=True,
            confidence=1,
            probabilities={name: float(name == e) for name in EMOTIONS},
        )
        for e in EMOTIONS
    ]
    samples.append(SimpleNamespace(emotion="fail_detection", face_detected=False))
    metrics = summarize(samples)
    assert metrics["sample_count"] == 7 and metrics["failed_samples"] == 1
    assert metrics["positive_ratio"] == pytest.approx(1 / 7)
    assert metrics["negative_ratio"] == pytest.approx(4 / 7)
    assert metrics["neutral_ratio"] == pytest.approx(2 / 7)
    assert sum(metrics["average_probabilities"].values()) == pytest.approx(1, abs=1e-5)


def test_register_login_refresh_rotation_and_logout(env):
    body = {"email": "New.User@example.com", "password": "Password123!", "full_name": "New User"}
    response = env.client.post("/auth/register", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["data"]["email"] == "new.user@example.com"
    assert env.client.post("/auth/register", json=body).status_code == 409
    assert (
        env.client.post(
            "/auth/login", json={"email": body["email"], "password": "WrongPass123"}
        ).status_code
        == 401
    )
    login = env.client.post(
        "/auth/login", json={"email": body["email"], "password": body["password"]}
    )
    assert login.status_code == 200, login.text
    tokens = login.json()["data"]
    assert (
        env.client.get(
            "/auth/me", headers={"Authorization": "Bearer " + tokens["access_token"]}
        ).status_code
        == 200
    )
    refresh = env.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 200, refresh.text
    assert (
        env.client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )
    rotated = refresh.json()["data"]
    assert (
        env.client.post(
            "/auth/logout", json={"refresh_token": rotated["refresh_token"]}
        ).status_code
        == 200
    )
    assert (
        env.client.post(
            "/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
        ).status_code
        == 401
    )


def test_expired_wrong_type_and_forged_role_tokens(env, room):
    token = issue_token("student", "access", env.settings)
    payload = jwt.decode(
        token, env.settings.jwt_secret, algorithms=["HS256"], audience=env.settings.jwt_audience
    )
    payload["role"] = "teacher"
    forged_role = jwt.encode(payload, env.settings.jwt_secret, algorithm="HS256")
    assert (
        env.client.get(
            f"/meetings/{room}/dashboard", headers={"Authorization": "Bearer " + forged_role}
        ).status_code
        == 403
    )
    payload["exp"] = int((now() - timedelta(minutes=1)).timestamp())
    expired = jwt.encode(payload, env.settings.jwt_secret, algorithm="HS256")
    assert (
        env.client.get("/auth/me", headers={"Authorization": "Bearer " + expired}).status_code
        == 401
    )
    refresh = issue_token("student", "refresh", env.settings)
    assert (
        env.client.get("/auth/me", headers={"Authorization": "Bearer " + refresh}).status_code
        == 401
    )


def test_log_pagination_time_filter_and_cross_meeting_id(env, room):
    service = EmotionService(env.factory, env.settings)
    start = now() - timedelta(seconds=20)
    ids = []
    for i, emotion in enumerate(("happy", "sad", "angry")):
        stamp = start + timedelta(seconds=i)
        sample_id, _ = service.save(
            room, env.users["student"], stamp, prediction(f"log-{i}", stamp, emotion)
        )
        ids.append(sample_id)
    path = f"/meetings/{room}/emotion-logs"
    response = env.client.get(
        path, params={"offset": 1, "limit": 1}, headers=env.headers["teacher"]
    )
    data = response.json()["data"]
    assert data["total"] == 3 and [s["id"] for s in data["items"]] == [ids[1]]
    filtered = env.client.get(
        path,
        params={
            "start": (start + timedelta(seconds=1)).isoformat(),
            "end": (start + timedelta(seconds=1)).isoformat(),
        },
        headers=env.headers["teacher"],
    )
    assert filtered.json()["data"]["total"] == 1
    second = env.client.post("/meetings", json={}, headers=env.headers["teacher"]).json()["data"][
        "id"
    ]
    assert (
        env.client.delete(
            f"/meetings/{second}/emotion-logs/{ids[0]}", headers=env.headers["teacher"]
        ).status_code
        == 404
    )
