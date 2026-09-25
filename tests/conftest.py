import base64
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

import mongomock
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.core.db import Base, make_database, now
from app.core.mongo import MongoDatabase, MongoSession
from app.core.security import issue_token
from app.integrations.ai import MockAIClient
from app.integrations.storage import UploadedVideo
from app.main import create_app
from app.modules.auth.model import User


class Storage:
    def __init__(self):
        self.documents = {}

    def upload(self, data, public_id):
        return UploadedVideo(public_id, "https://storage.test/video", 30, len(data), "mp4")

    def delete(self, public_id):
        pass

    def download_url(self, public_id, format, expires_in=300):
        return "https://storage.test/signed-video"

    def upload_document(self, data, public_id):
        self.documents[public_id] = data

    def delete_document(self, public_id):
        self.documents.pop(public_id, None)

    def document_download_url(self, public_id):
        return "https://storage.test/signed-document"


@pytest.fixture(params=["sqlite", "mongo"])
def env(request, tmp_path):
    settings = Settings(
        _env_file=None,
        jwt_secret="test-secret-" * 4,
        ai_mode="mock",
        database_url="sqlite://",
        bcrypt_rounds=4,
    )
    engine = None
    if request.param == "sqlite":
        engine, factory = make_database(f"sqlite:///{tmp_path / 'test.db'}")
        Base.metadata.create_all(engine)
    else:
        database = mongomock.MongoClient(tz_aware=True).test
        indexes = MongoDatabase("mongodb://unused/test")
        indexes.database = database
        indexes.ensure_indexes()

        @contextmanager
        def factory():
            yield MongoSession(database)

    users = {}
    with factory() as db:
        for name, role in [
            ("teacher", "teacher"),
            ("student", "student"),
            ("other", "student"),
            ("outsider", "teacher"),
        ]:
            users[name] = User(
                id=name,
                email=f"{name}@example.test",
                password_hash="unused",
                full_name=name,
                role=role,
                created_at=now(),
            )
            db.add(users[name])
        db.commit()
    tokens = {name: issue_token(name, "access", settings) for name in users}
    headers = {name: {"Authorization": f"Bearer {token}"} for name, token in tokens.items()}
    app = create_app(settings, factory, MockAIClient(), Storage())
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            app=app,
            settings=settings,
            factory=factory,
            users=users,
            tokens=tokens,
            headers=headers,
        )
    if engine:
        engine.dispose()


@pytest.fixture
def room(env):
    response = env.client.post("/meetings", json={}, headers=env.headers["teacher"])
    assert response.status_code == 201, response.text
    room_id = response.json()["data"]["id"]
    response = env.client.post(f"/meetings/{room_id}/join", headers=env.headers["student"])
    assert response.status_code == 200, response.text
    return room_id


@pytest.fixture
def frame_data():
    buffer = BytesIO()
    Image.new("RGB", (32, 32)).save(buffer, format="JPEG")
    return {
        "frame_id": "frame-1",
        "timestamp": now().isoformat(),
        "content_type": "image/jpeg",
        "frame_base64": base64.b64encode(buffer.getvalue()).decode(),
    }
