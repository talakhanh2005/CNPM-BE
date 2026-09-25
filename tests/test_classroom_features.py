import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from zipfile import ZipFile

import httpx
import pytest
from fastapi import WebSocketDisconnect
from pydantic import ValidationError

from app.core.config import Settings
from app.core.db import now
from app.core.errors import AppError
from app.integrations.ai import HttpAIClient, MockAIClient
from app.integrations.ai_schema import EMOTIONS, FrameResult
from app.modules.analysis.service import process_one
from app.modules.emotions.service import EmotionService
from app.modules.meetings.model import Participant
from app.modules.meetings.service import MeetingService
from app.modules.recordings.repository import RecordingRepository


def connect(ws, token):
    ws.send_json({"type": "AUTH", "token": token})
    assert ws.receive_json()["data"]["type"] == "JOIN"


def result(frame_id, timestamp, emotion="happy"):
    return FrameResult(
        frame_id=frame_id,
        timestamp=timestamp,
        emotion=emotion,
        confidence=0.8,
        face_detected=True,
        face_id="face-1",
        probabilities={e: 0.8 if e == emotion else 0.2 / 6 for e in EMOTIONS},
    )


def test_room_has_one_student_for_lifetime(env, room):
    assert (
        env.client.post(f"/meetings/{room}/join", headers=env.headers["other"]).status_code == 409
    )
    assert (
        env.client.post(f"/meetings/{room}/join", headers=env.headers["outsider"]).status_code
        == 403
    )
    env.client.post(f"/meetings/{room}/leave", headers=env.headers["student"])
    assert (
        env.client.post(f"/meetings/{room}/join", headers=env.headers["other"]).status_code == 409
    )
    assert (
        env.client.post(f"/meetings/{room}/join", headers=env.headers["student"]).status_code == 200
    )


def test_concurrent_student_join(env):
    room = env.client.post("/meetings", json={}, headers=env.headers["teacher"]).json()["data"][
        "id"
    ]

    def join(name):
        with env.factory() as db:
            try:
                MeetingService(db).join(room, env.users[name])
                return 200
            except AppError as exc:
                return exc.status

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(join, ["student", "other"])) == [200, 409]


def test_frame_permissions_and_metadata(env, room, frame_data):
    path = f"/meetings/{room}/frames"
    for name in ["teacher", "other"]:
        assert env.client.post(path, json=frame_data, headers=env.headers[name]).status_code == 403
    response = env.client.post(path, json=frame_data, headers=env.headers["student"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["frame_id"] == frame_data["frame_id"]
    assert data["face_detected"] and len(data["probabilities"]) == 7 and data["logged"]
    assert env.client.post(path, json=frame_data, headers=env.headers["student"]).status_code == 429
    env.client.post(f"/meetings/{room}/leave", headers=env.headers["student"])
    assert env.client.post(path, json=frame_data, headers=env.headers["student"]).status_code == 409


def test_log_state_change_90_seconds_and_stale_response(env, room):
    service = EmotionService(env.factory, env.settings)
    start = now()
    outcomes = []
    for seconds, emotion in [
        (0, "happy"),
        (20, "happy"),
        (89, "happy"),
        (90, "happy"),
        (91, "sad"),
        (80, "angry"),
        (92, "sad"),
    ]:
        timestamp = start + timedelta(seconds=seconds)
        outcomes.append(
            service.save(
                room, env.users["student"], timestamp, result(str(seconds), timestamp, emotion)
            )[1]
        )
    assert outcomes == [True, False, False, True, True, False, False]
    logs = env.client.get(f"/meetings/{room}/emotion-logs", headers=env.headers["teacher"])
    assert len(logs.json()["data"]["items"]) == 3
    assert (
        env.client.get(f"/meetings/{room}/emotion-logs", headers=env.headers["student"]).status_code
        == 403
    )


def test_ai_failure_saved_and_report_handles_no_face(env, room, frame_data):
    class BrokenAI:
        async def analyze_frame(self, *args):
            raise RuntimeError("unavailable")

    env.app.state.ai = BrokenAI()
    response = env.client.post(
        f"/meetings/{room}/frames", json=frame_data, headers=env.headers["student"]
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["emotion"] == "fail_detection" and data["failure_reason"] == "ai_error"
    assert not data["face_detected"] and set(data["probabilities"].values()) == {0}
    report = env.client.get(f"/meetings/{room}/report", headers=env.headers["teacher"])
    assert report.status_code == 200, report.text
    assert report.json()["data"]["sample_count"] == 0
    assert report.json()["data"]["timeline_total"] == 1


def test_websocket_frames_reconnect_and_teacher_rejection(env, room, frame_data):
    path = f"/ws/meetings/{room}"
    with env.client.websocket_connect(path) as teacher:
        connect(teacher, env.tokens["teacher"])
        teacher.send_json({"type": "FRAME", "payload": frame_data})
        assert teacher.receive_json()["data"]["code"] == "FORBIDDEN"
        with env.client.websocket_connect(path) as old:
            connect(old, env.tokens["student"])
            assert teacher.receive_json()["data"]["type"] == "JOIN"
            with env.client.websocket_connect(path) as student:
                connect(student, env.tokens["student"])
                assert teacher.receive_json()["data"]["type"] == "JOIN"
                with pytest.raises(WebSocketDisconnect) as exc:
                    old.receive_json()
                assert exc.value.code == 4001
                student.send_json({"type": "FRAME", "payload": frame_data})
                assert teacher.receive_json()["data"]["type"] == "EMOTION"
                assert student.receive_json()["data"]["type"] == "FRAME_RESULT"
                teacher.send_json({"type": "CAMERA_STATUS", "payload": {"enabled": True}})
                assert student.receive_json()["data"]["sender_id"] == "teacher"
        # A refresh after transport disconnection can authenticate without rejoining.
        with env.client.websocket_connect(path) as student:
            connect(student, env.tokens["student"])
    with env.factory() as db:
        assert db.get(Participant, (room, "student")).status == "joined"


def test_after_session_upload_auto_analysis_and_history(env, frame_data):
    room = env.client.post(
        "/meetings", json={"mode": "after_session"}, headers=env.headers["teacher"]
    ).json()["data"]["id"]
    env.client.post(f"/meetings/{room}/join", headers=env.headers["student"])
    assert (
        env.client.post(
            f"/meetings/{room}/frames", json=frame_data, headers=env.headers["student"]
        ).status_code
        == 409
    )
    env.client.post(f"/meetings/{room}/end", headers=env.headers["teacher"])
    response = env.client.post(
        f"/meetings/{room}/recordings",
        content=b"\x00\x00\x00\x20ftypisom",
        headers={**env.headers["teacher"], "Content-Type": "video/mp4"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["status"] == "pending"
    history = env.client.get("/meetings?mode=after_session", headers=env.headers["teacher"])
    assert history.json()["data"]["items"][0]["analysis_status"] == "pending"
    assert asyncio.run(
        process_one(env.factory, env.app.state.ai, env.app.state.storage, env.settings)
    )
    history = env.client.get("/meetings", headers=env.headers["teacher"])
    assert history.json()["data"]["items"][0]["analysis_status"] == "completed"
    assert (
        env.client.get("/meetings", headers=env.headers["outsider"]).json()["data"]["items"] == []
    )
    report = env.client.get(f"/meetings/{room}/report", headers=env.headers["teacher"])
    assert report.json()["data"]["sample_count"] == 20


def test_material_upload_download_and_access(env, room):
    headers = {**env.headers["teacher"], "Content-Type": "application/pdf"}
    path = f"/meetings/{room}/materials?filename=lesson.pdf"
    response = env.client.post(path, content=b"%PDF-1.7\nexample", headers=headers)
    assert response.status_code == 201, response.text
    material = response.json()["data"]
    assert "public_id" not in material
    download = f"/materials/{material['id']}/download"
    assert env.client.get(download, headers=env.headers["student"]).status_code == 200
    assert env.client.get(download, headers=env.headers["other"]).status_code == 403
    assert (
        env.client.get(f"/meetings/{room}/materials", headers=env.headers["student"]).json()[
            "data"
        ][0]["id"]
        == material["id"]
    )
    assert env.client.post(path, content=b"fake pdf", headers=headers).status_code == 415
    assert (
        env.client.post(
            path,
            content=b"%PDF-1.7",
            headers={**env.headers["student"], "Content-Type": "application/pdf"},
        ).status_code
        == 403
    )
    env.settings.max_document_bytes = 1024
    assert env.client.post(path, content=b"%PDF-" + b"x" * 1024, headers=headers).status_code == 413


def test_pptx_container(env, room):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/presentation.xml", "<presentation/>")
    response = env.client.post(
        f"/meetings/{room}/materials?filename=slides.pptx",
        content=buffer.getvalue(),
        headers={
            **env.headers["teacher"],
            "Content-Type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        },
    )
    assert response.status_code == 201, response.text


def test_ice_config_requires_active_membership(env, room):
    env.settings.ice_servers = [
        {"urls": "turn:turn.example.test:3478", "username": "user", "credential": "pass"}
    ]
    response = env.client.get(f"/meetings/{room}/ice-config", headers=env.headers["student"])
    assert response.json()["data"]["turn_configured"]
    assert (
        env.client.get(f"/meetings/{room}/ice-config", headers=env.headers["other"]).status_code
        == 403
    )


@pytest.mark.asyncio
async def test_http_ai_frame_contract():
    timestamp = now()

    def handler(request):
        body = request.read()
        assert b'name="frame_id"' in body and b"frame-42" in body
        assert timestamp.isoformat().encode() in body
        return httpx.Response(200, json=result("frame-42", timestamp).model_dump(mode="json"))

    settings = Settings(_env_file=None, jwt_secret="test-secret" * 4)
    assert settings.ai_mode == "http"
    client = HttpAIClient(settings, httpx.MockTransport(handler))
    assert (
        await client.analyze_frame(b"image", "image/jpeg", "frame-42", timestamp)
    ).face_id == "face-1"


def test_probability_contract():
    data = result("1", now()).model_dump()
    data["probabilities"].pop("happy")
    with pytest.raises(ValidationError):
        FrameResult.model_validate(data)
    no_face = FrameResult.failed("2", now(), reason="no_face")
    assert not no_face.face_detected and no_face.emotion == "fail_detection"


def test_slow_ai_does_not_block_signaling(env, room, frame_data):
    class SlowAI(MockAIClient):
        async def analyze_frame(self, *args):
            await asyncio.sleep(0.3)
            return await super().analyze_frame(*args)

    env.app.state.ai = SlowAI()
    path = f"/ws/meetings/{room}"
    with env.client.websocket_connect(path) as teacher:
        connect(teacher, env.tokens["teacher"])
        with env.client.websocket_connect(path) as student:
            connect(student, env.tokens["student"])
            teacher.receive_json()
            student.send_json({"type": "FRAME", "payload": frame_data})
            student.send_json({"type": "CAMERA_STATUS", "payload": {"enabled": False}})
            assert teacher.receive_json()["data"]["type"] == "CAMERA_STATUS"
            assert teacher.receive_json()["data"]["type"] == "EMOTION"
            assert student.receive_json()["data"]["type"] == "FRAME_RESULT"


def test_end_during_ai_prevents_save(env, room, frame_data):
    from threading import Event

    started = Event()

    class SlowAI(MockAIClient):
        async def analyze_frame(self, *args):
            started.set()
            await asyncio.sleep(0.3)
            return await super().analyze_frame(*args)

    env.app.state.ai = SlowAI()
    with ThreadPoolExecutor(1) as pool:
        response = pool.submit(
            env.client.post,
            f"/meetings/{room}/frames",
            json=frame_data,
            headers=env.headers["student"],
        )
        assert started.wait(2)
        assert (
            env.client.post(f"/meetings/{room}/end", headers=env.headers["teacher"]).status_code
            == 200
        )
        assert response.result().status_code == 409
    assert (
        env.client.get(f"/meetings/{room}/emotion-logs", headers=env.headers["teacher"]).json()[
            "data"
        ]["items"]
        == []
    )


def test_worker_recovers_upload_without_job(env):
    room = env.client.post(
        "/meetings", json={"mode": "after_session"}, headers=env.headers["teacher"]
    ).json()["data"]["id"]
    with env.factory() as db:
        RecordingRepository(db).add(
            meeting_id=room,
            cloudinary_url="https://storage.test/video",
            public_id="uploaded-before-crash",
            format="mp4",
            duration=30,
            size_bytes=12,
            status="uploaded",
        )
        db.commit()
    assert asyncio.run(
        process_one(env.factory, env.app.state.ai, env.app.state.storage, env.settings)
    )
    history = env.client.get("/meetings", headers=env.headers["teacher"]).json()["data"]["items"]
    assert history[0]["analysis_status"] == "completed"


def test_three_frames_per_second(env, room, frame_data):
    import time

    for index in range(3):
        if index:
            time.sleep(0.34)
        response = env.client.post(
            f"/meetings/{room}/frames",
            json={**frame_data, "frame_id": str(index)},
            headers=env.headers["student"],
        )
        assert response.status_code == 200, response.text


def test_no_face_is_logged_and_recovery_is_state_change(env, room, frame_data):
    class NoFaceAI:
        async def analyze_frame(self, frame, content_type, frame_id, timestamp):
            return FrameResult.failed(frame_id, timestamp, "no_face")

    env.app.state.ai = NoFaceAI()
    path = f"/meetings/{room}/frames"
    response = env.client.post(path, json=frame_data, headers=env.headers["student"])
    assert response.json()["data"]["failure_reason"] == "no_face"
    env.app.state.frame_limiter.entries.clear()
    env.app.state.ai = MockAIClient()
    response = env.client.post(
        path, json={**frame_data, "frame_id": "back"}, headers=env.headers["student"]
    )
    assert response.json()["data"]["logged"] and response.json()["data"]["face_detected"]


def test_rest_and_websocket_share_rate_limit(env, room, frame_data):
    with env.client.websocket_connect(f"/ws/meetings/{room}") as student:
        connect(student, env.tokens["student"])
        assert (
            env.client.post(
                f"/meetings/{room}/frames", json=frame_data, headers=env.headers["student"]
            ).status_code
            == 200
        )
        student.send_json({"type": "FRAME", "payload": frame_data})
        assert student.receive_json()["data"]["code"] == "RATE_LIMITED"


def test_websocket_accepts_frame_above_old_64k_limit(env, room, frame_data):
    import base64
    import random

    from PIL import Image

    image = Image.frombytes("RGB", (256, 256), random.Random(1).randbytes(256 * 256 * 3))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = {
        **frame_data,
        "frame_base64": base64.b64encode(buffer.getvalue()).decode(),
        "content_type": "image/png",
    }
    assert len(payload["frame_base64"]) > 65536
    with env.client.websocket_connect(f"/ws/meetings/{room}") as student:
        connect(student, env.tokens["student"])
        student.send_json({"type": "FRAME", "payload": payload})
        assert student.receive_json()["data"]["type"] == "FRAME_RESULT"


def test_one_socket_per_user_across_rooms(env, room):
    second = env.client.post("/meetings", json={}, headers=env.headers["teacher"]).json()["data"][
        "id"
    ]
    env.client.post(f"/meetings/{second}/join", headers=env.headers["student"])
    with env.client.websocket_connect(f"/ws/meetings/{room}") as teacher:
        connect(teacher, env.tokens["teacher"])
        with env.client.websocket_connect(f"/ws/meetings/{room}") as old:
            connect(old, env.tokens["student"])
            teacher.receive_json()
            with env.client.websocket_connect(f"/ws/meetings/{second}") as new:
                connect(new, env.tokens["student"])
                assert teacher.receive_json()["data"]["type"] == "LEAVE"
                with pytest.raises(WebSocketDisconnect):
                    old.receive_json()
                teacher.send_json(
                    {
                        "type": "OFFER",
                        "target_id": "student",
                        "payload": {"type": "offer", "sdp": "v=0"},
                    }
                )
                assert teacher.receive_json()["data"]["code"] == "PEER_OFFLINE"
