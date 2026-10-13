"""Features merged from BE A into the BE B application (run on SQLite and MongoDB)."""

import logging
from datetime import timedelta

from app.core.config import Settings
from app.core.db import now
from app.integrations.storage import CloudinaryStorage
from app.main import RedactShareTokenFilter
from app.modules.auth.model import User
from app.modules.materials.model import Material
from app.modules.meetings.model import Meeting, Participant

PDF = b"%PDF-1.7\nexample"
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def create(env, **body):
    response = env.client.post("/meetings", json=body, headers=env.headers["teacher"])
    assert response.status_code == 201, response.text
    return response.json()["data"]


def join(env, room, name="student"):
    response = env.client.post(f"/meetings/{room}/join", headers=env.headers[name])
    assert response.status_code == 200, response.text


def upload_doc(env, room, content=PDF, filename="lesson.pdf", mime="application/pdf", tags=None):
    data = {"tags": tags} if tags else {}
    return env.client.post(
        f"/meetings/{room}/documents",
        files={"file": (filename, content, mime)},
        data=data,
        headers=env.headers["teacher"],
    )


# ---------------------------------------------------------------- auth / users


def test_teacher_whitelist_and_invite_rules(env):
    env.settings.teacher_email_whitelist = "Boss@School.com"
    body = {"email": "boss@school.com", "password": "password123", "full_name": "Boss"}
    response = env.client.post("/auth/register", json={**body, "role": "student"})
    assert response.status_code == 201, response.text
    assert response.json()["data"]["role"] == "teacher"
    response = env.client.post(
        "/auth/register",
        json={
            "email": "x@school.com",
            "password": "password123",
            "full_name": "X",
            "role": "teacher",
        },
    )
    assert response.status_code == 403
    assert response.json()["data"]["code"] == "TEACHER_INVITE_REQUIRED"


def test_v1_register_login_profile_and_admin(env):
    response = env.client.post(
        "/v1/auth/register",
        json={"email": "New@Example.com", "password": "password123", "display_name": "Newbie"},
    )
    assert response.status_code == 201, response.text
    user = response.json()["data"]
    assert user["role"] == "student" and user["display_name"] == "Newbie"
    login = env.client.post(
        "/v1/auth/login", data={"username": "new@example.com", "password": "password123"}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]  # raw body for Swagger's OAuth2 password flow
    headers = {"Authorization": f"Bearer {token}"}
    profile = env.client.put("/v1/users/me", json={"display_name": "Renamed"}, headers=headers)
    assert profile.json()["data"]["full_name"] == "Renamed"
    env.client.post(
        "/v1/auth/register", json={"email": "taken@example.com", "password": "password123"}
    )
    taken = env.client.put("/v1/users/me", json={"email": "Taken@example.com"}, headers=headers)
    assert taken.status_code == 409
    assert env.client.get("/v1/users", headers=headers).status_code == 403

    with env.factory() as db:
        db.add(
            User(
                id="admin",
                email="admin@example.test",
                password_hash="unused",
                full_name="Admin",
                role="admin",
                created_at=now(),
            )
        )
        db.commit()
    from app.core.security import issue_token

    admin = {"Authorization": f"Bearer {issue_token('admin', 'access', env.settings)}"}
    listed = env.client.get("/v1/users", headers=admin).json()["data"]
    assert "new@example.com" in {item["email"] for item in listed}
    promoted = env.client.put(f"/v1/users/{user['id']}", json={"role": "teacher"}, headers=admin)
    assert promoted.json()["data"]["role"] == "teacher"
    assert (
        env.client.put("/v1/users/admin", json={"role": "student"}, headers=admin).status_code
        == 400
    )
    assert env.client.delete("/v1/users/admin", headers=admin).status_code == 400
    assert env.client.delete(f"/v1/users/{user['id']}", headers=admin).status_code == 200
    assert env.client.get(f"/v1/users/{user['id']}", headers=admin).status_code == 404


def test_admin_seeded_at_startup(env):
    from pydantic import SecretStr

    from app.modules.auth.service import AuthService

    settings = env.settings.model_copy(
        update={"admin_email": "Root@Example.com", "admin_password": SecretStr("root-password-1")}
    )
    with env.factory() as db:
        assert AuthService(db, settings).ensure_admin()
        assert not AuthService(db, settings).ensure_admin()  # never duplicated
    response = env.client.post(
        "/auth/login", json={"email": "root@example.com", "password": "root-password-1"}
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------- meetings


def test_create_with_room_metadata_and_legacy_fields(env):
    room = create(env, name=" Toán 10A ", participantMode="approval", analysisMode="batch")
    assert room["name"] == "Toán 10A"
    assert room["participant_mode"] == "approval"
    assert room["mode"] == "after_session"
    assert room["recording_status"] == "none"
    assert create(env)["name"] == "Lớp học trực tuyến"


def test_update_and_soft_delete_are_owner_only(env, room):
    path = f"/meetings/{room}"
    payload = {"name": "Văn", "description": "Ôn tập", "tags": ["van", "van", " 10a "]}
    for name in ["student", "outsider"]:
        assert env.client.put(path, json=payload, headers=env.headers[name]).status_code == 404
    response = env.client.put(path, json=payload, headers=env.headers["teacher"])
    assert response.status_code == 200, response.text
    assert response.json()["data"]["tags"] == ["van", "10a"]
    assert env.client.put(path, json={}, headers=env.headers["teacher"]).status_code == 422
    assert (
        env.client.put(path, json={"name": " "}, headers=env.headers["teacher"]).status_code == 422
    )

    code = env.client.get(path, headers=env.headers["teacher"]).json()["data"]["code"]
    assert env.client.delete(path, headers=env.headers["student"]).status_code == 404
    assert env.client.delete(path, headers=env.headers["teacher"]).status_code == 200
    assert env.client.get(path, headers=env.headers["teacher"]).status_code == 404
    assert (
        env.client.post(
            "/meetings/join", json={"code": code}, headers=env.headers["other"]
        ).status_code
        == 404
    )
    assert env.client.get("/meetings", headers=env.headers["teacher"]).json()["data"]["items"] == []
    assert env.client.delete(path, headers=env.headers["teacher"]).status_code == 404


def test_filtered_history_for_teacher_and_student(env, room):
    other = create(env, name="Hoá học")["id"]
    env.client.post(f"/meetings/{other}/end", headers=env.headers["teacher"])
    teacher = env.headers["teacher"]
    everything = env.client.get("/meetings/history", headers=teacher).json()["data"]
    assert isinstance(everything, list) and len(everything) == 2
    closed = env.client.get("/meetings/history?status=closed", headers=teacher).json()["data"]
    assert [item["id"] for item in closed] == [other]
    found = env.client.get("/meetings/history?q=HOÁ", headers=teacher).json()["data"]
    assert [item["id"] for item in found] == [other]
    paged = env.client.get("/meetings/history?page=1&size=1", headers=teacher).json()["data"]
    assert paged["pagination"] == {"page": 1, "size": 1, "total": 2, "total_pages": 2}
    today = now().date().isoformat()
    assert (
        len(env.client.get(f"/meetings/history?to_date={today}", headers=teacher).json()["data"])
        == 2
    )
    assert env.client.get("/meetings/history?page=0", headers=teacher).status_code == 422
    student = env.client.get("/meetings/history", headers=env.headers["student"]).json()["data"]
    assert [item["id"] for item in student] == [room]
    assert env.client.get("/meetings/history", headers=env.headers["other"]).json()["data"] == []


def test_disconnect_then_reopen_rejoins(env, room):
    path = f"/meetings/{room}"
    response = env.client.post(f"{path}/disconnect", headers=env.headers["student"])
    assert response.json()["data"]["status"] == "disconnected"
    with env.factory() as db:
        assert db.get(Participant, (room, "student")).status == "disconnected"
    # Disconnected members are not active (ice-config requires an active member).
    assert env.client.get(f"{path}/ice-config", headers=env.headers["student"]).status_code == 409
    assert env.client.get(path, headers=env.headers["student"]).status_code == 200
    assert env.client.get(f"{path}/ice-config", headers=env.headers["student"]).status_code == 200
    ignored = env.client.post(f"{path}/disconnect", headers=env.headers["other"])
    assert ignored.json()["data"]["status"] == "ignored"


def test_recording_metadata_times_out_without_ai(env, room):
    path = f"/meetings/{room}/recording"
    assert (
        env.client.post(
            path, json={"durationSeconds": 600}, headers=env.headers["other"]
        ).status_code
        == 404
    )
    response = env.client.post(path, json={"durationSeconds": 600}, headers=env.headers["student"])
    data = response.json()["data"]
    assert data["recording_status"] == "processing" and data["duration_minutes"] == 10
    with env.factory() as db:
        meeting = db.get(Meeting, room)
        meeting.processing_started_at = now() - timedelta(minutes=6)
        db.commit()
    data = env.client.get(f"/meetings/{room}", headers=env.headers["teacher"]).json()["data"]
    assert data["recording_status"] == "failed"
    assert data["failed_reason"] == "timeout_waiting_ai"


def test_recording_file_and_media_endpoints(env, room):
    path = f"/meetings/{room}/recording-file"
    bad = env.client.post(
        path, files={"file": ("rec.webm", b"MZ fake", "video/webm")}, headers=env.headers["teacher"]
    )
    assert bad.status_code == 415
    response = env.client.post(
        path, files={"file": ("rec.webm", WEBM, "video/webm")}, headers=env.headers["teacher"]
    )
    assert response.status_code == 200, response.text
    public_id = response.json()["data"]["public_id"]
    meeting = env.client.get(f"/meetings/{room}", headers=env.headers["student"]).json()["data"]
    assert meeting["recording_status"] == "processing"
    assert env.client.get(f"/media/{public_id}", headers=env.headers["student"]).status_code == 200
    assert env.client.get(f"/media/{public_id}", headers=env.headers["other"]).status_code == 404
    assert (
        env.client.delete(f"/media/{public_id}", headers=env.headers["student"]).status_code == 404
    )
    deleted = env.client.delete(f"/media/{public_id}", headers=env.headers["teacher"])
    assert deleted.json()["data"]["deleted"] is True
    meeting = env.client.get(f"/meetings/{room}", headers=env.headers["teacher"]).json()["data"]
    assert meeting["recording_status"] == "none"


def test_signed_upload_parameters(env):
    settings = Settings(
        _env_file=None,
        jwt_secret="test-secret-" * 4,
        cloudinary_cloud_name="demo",
        cloudinary_api_key="key",
        cloudinary_api_secret="secret",
    )
    env.app.state.storage = CloudinaryStorage(settings)
    response = env.client.post(
        "/media/signed-upload",
        json={"folder": "avatars", "resource_type": "image"},
        headers=env.headers["student"],
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["folder"] == "openemotion/uploads/student/avatars"
    assert data["upload_url"].endswith("/demo/image/upload") and data["signature"]
    for body in [{"folder": "../x"}, {"resource_type": "exe"}, {"max_bytes": True}]:
        assert (
            env.client.post(
                "/media/signed-upload", json=body, headers=env.headers["student"]
            ).status_code
            == 422
        )
    unknown = env.client.post(
        "/media/signed-upload", json={"allowed_formats": ["exe"]}, headers=env.headers["student"]
    )
    assert unknown.status_code == 415


def test_ice_config_falls_back_to_stun_settings(env, room):
    data = env.client.get(f"/meetings/{room}/ice-config", headers=env.headers["student"]).json()[
        "data"
    ]
    assert data["iceServers"] == [{"urls": ["stun:stun.l.google.com:19302"]}]
    assert not data["turn_configured"]


# ---------------------------------------------------------------- documents


def test_document_private_until_shared(env, room):
    join(env, room, "other")
    response = upload_doc(env, room, tags="toan, slide, toan")
    assert response.status_code == 201, response.text
    document = response.json()["data"]
    assert document["tags"] == ["toan", "slide"] and document["download_url"]
    doc_path = f"/meetings/{room}/documents/{document['id']}"
    listing = f"/meetings/{room}/documents"
    assert env.client.get(listing, headers=env.headers["student"]).json()["data"]["items"] == []
    assert env.client.get(doc_path, headers=env.headers["student"]).status_code == 404

    shared = env.client.patch(
        f"{doc_path}/share", json={"account_ids": ["student"]}, headers=env.headers["teacher"]
    )
    assert shared.json()["data"]["shared_with"] == ["student"]
    assert env.client.get(doc_path, headers=env.headers["student"]).status_code == 200
    assert env.client.get(doc_path, headers=env.headers["other"]).status_code == 404
    bad = env.client.patch(
        f"{doc_path}/share", json={"account_ids": ["outsider"]}, headers=env.headers["teacher"]
    )
    assert bad.status_code == 422
    env.client.patch(f"{doc_path}/share", json={"account_ids": []}, headers=env.headers["teacher"])
    assert env.client.get(doc_path, headers=env.headers["other"]).status_code == 200
    # B's material endpoints apply the same sharing rules.
    assert (
        env.client.get(
            f"/materials/{document['id']}/download", headers=env.headers["other"]
        ).status_code
        == 200
    )
    env.client.patch(
        f"{doc_path}/unshare", json={"account_ids": []}, headers=env.headers["teacher"]
    )
    assert env.client.get(doc_path, headers=env.headers["other"]).status_code == 404
    assert (
        env.client.get(f"/meetings/{room}/materials", headers=env.headers["other"]).json()["data"]
        == []
    )
    assert (
        env.client.patch(f"{doc_path}/share", json={}, headers=env.headers["student"]).status_code
        == 404
    )


def test_document_revoke_restore_and_public_link(env, room):
    document = upload_doc(env, room).json()["data"]
    doc_path = f"/meetings/{room}/documents/{document['id']}"
    teacher = env.headers["teacher"]
    env.client.patch(f"{doc_path}/share", json={"account_ids": []}, headers=teacher)
    link = env.client.post(
        f"{doc_path}/generate-share-link", json={"expires_in_hours": 2}, headers=teacher
    )
    assert link.status_code == 200, link.text
    share = link.json()["data"]["share_path"]
    public = env.client.get(share)
    assert public.status_code == 200 and public.headers["cache-control"] == "no-store"
    assert "shared_with" not in public.json()["data"]
    assert (
        env.client.post(
            f"{doc_path}/generate-share-link", json={"expires_in_hours": 0}, headers=teacher
        ).status_code
        == 422
    )

    revoked = env.client.post(f"{doc_path}/revoke", headers=teacher)
    assert revoked.json()["data"]["revoked"] is True
    assert env.client.get(share).status_code == 410
    assert env.client.get(doc_path, headers=env.headers["student"]).status_code == 404
    assert env.client.post(f"{doc_path}/generate-share-link", headers=teacher).status_code == 409
    teacher_list = env.client.get(
        f"/meetings/{room}/documents?include_revoked=false", headers=teacher
    )
    assert teacher_list.json()["data"]["items"] == []
    env.client.post(f"{doc_path}/restore", headers=teacher)
    assert env.client.get(share).status_code == 200

    with env.factory() as db:
        material = db.get(Material, document["id"])
        material.share_expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert env.client.get(share).status_code == 410
    assert env.client.get("/share/documents/unknown-token").status_code == 404


def test_document_filters_limit_and_delete(env, room):
    upload_doc(env, room, filename="Bai-giang.pdf", tags="toan")
    upload_doc(env, room, content=PNG, filename="hinh.png", mime="image/png", tags="anh")
    teacher = env.headers["teacher"]
    listing = f"/meetings/{room}/documents"
    assert (
        env.client.get(f"{listing}?q=GIANG", headers=teacher).json()["data"]["pagination"]["total"]
        == 1
    )
    tagged = env.client.get(f"{listing}?tag=anh", headers=teacher).json()["data"]["items"]
    assert [item["filename"] for item in tagged] == ["hinh.png"]
    assert env.client.get(listing, headers=env.headers["outsider"]).status_code == 404
    assert upload_doc(env, room, content=b"MZ", filename="virus.pdf").status_code == 415

    env.settings.max_documents_per_meeting = 2
    assert upload_doc(env, room).status_code == 400
    raw = env.client.post(
        f"/meetings/{room}/materials?filename=extra.pdf",
        content=PDF,
        headers={**teacher, "Content-Type": "application/pdf"},
    )
    assert raw.json()["data"]["code"] == "DOCUMENT_LIMIT_REACHED"

    document_id = tagged[0]["id"]
    env.app.state.storage.fail_delete = True
    assert env.client.delete(f"{listing}/{document_id}", headers=teacher).status_code == 502
    env.app.state.storage.fail_delete = False
    assert env.client.delete(f"{listing}/{document_id}", headers=teacher).status_code == 200
    assert env.client.get(f"{listing}/{document_id}", headers=teacher).status_code == 404


# ---------------------------------------------------------------- v1 emotions, health, logs


def test_v1_emotion_labels_are_private(env):
    student = env.headers["student"]
    created = env.client.post(
        "/v1/emotions",
        data={"label": " happy "},
        files={"media_file": ("a.png", PNG, "image/png")},
        headers=student,
    )
    assert created.status_code == 201, created.text
    label = created.json()["data"]
    assert label["label"] == "happy" and label["media_url"]
    plain = env.client.post("/v1/emotions", data={"label": "calm"}, headers=student)
    assert plain.json()["data"]["media_url"] is None
    assert [
        item["label"] for item in env.client.get("/v1/emotions", headers=student).json()["data"]
    ] == ["calm", "happy"]
    assert (
        env.client.get(f"/v1/emotions/{label['id']}", headers=env.headers["other"]).status_code
        == 404
    )
    assert env.client.post("/v1/emotions", data={"label": "  "}, headers=student).status_code == 422
    assert env.client.delete(f"/v1/emotions/{label['id']}", headers=student).status_code == 200
    assert env.client.get(f"/v1/emotions/{label['id']}", headers=student).status_code == 404


def test_health_root_and_share_token_redaction(env):
    health = env.client.get("/health").json()["data"]
    assert health["status"] == "ok" and health["version"] == "2.0.0" and health["time"]
    assert env.client.get("/").json()["data"]["message"] == "Hello FastAPI"
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s",
        ("GET", "/api/share/documents/SECRET?x=1"),
        None,
    )
    RedactShareTokenFilter().filter(record)
    assert record.args[1] == "/api/share/documents/***?x=1"
