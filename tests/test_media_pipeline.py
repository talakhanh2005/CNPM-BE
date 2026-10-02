"""End-to-end checks for the Cloudinary media pipeline in emotions.py.

These tests exercise the real ``upload_media``/``delete_media`` code paths
(validation, metadata storage, cleanup) by stubbing only the Cloudinary HTTP
calls, so they run without real credentials or network access.
"""

from collections.abc import AsyncIterator, Iterator
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pydantic import SecretStr

import cloudinary.uploader
from cnpm_be.config import Settings
from cnpm_be.main import create_app


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def sort(self, key: str, direction: int) -> "FakeCursor":
        self.documents.sort(key=lambda document: document.get(key), reverse=direction < 0)
        return self

    def skip(self, offset: int) -> "FakeCursor":
        self.documents = self.documents[offset:]
        return self

    def limit(self, limit: int) -> "FakeCursor":
        self.documents = self.documents[:limit]
        return self

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async def iterate() -> AsyncIterator[dict[str, Any]]:
            for document in self.documents:
                yield deepcopy(document)

        return iterate()


class FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    @staticmethod
    def matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
        return all(document.get(key) == value for key, value in query.items())

    async def create_index(self, *_: Any, **__: Any) -> None:
        return None

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        document = next((item for item in self.documents if self.matches(item, query)), None)
        return deepcopy(document) if document is not None else None

    async def insert_one(self, document: dict[str, Any]) -> SimpleNamespace:
        stored = deepcopy(document)
        stored.setdefault("_id", ObjectId())
        self.documents.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def delete_one(self, query: dict[str, Any]) -> SimpleNamespace:
        document = next((item for item in self.documents if self.matches(item, query)), None)
        if document is not None:
            self.documents.remove(document)
        return SimpleNamespace(deleted_count=int(document is not None))

    def find(self, query: dict[str, Any] | None = None) -> FakeCursor:
        query = query or {}
        return FakeCursor([deepcopy(item) for item in self.documents if self.matches(item, query)])


class FakeDatabase:
    def __init__(self) -> None:
        self.users = FakeCollection()
        self.emotions = FakeCollection()

    async def command(self, *_: Any, **__: Any) -> dict[str, int]:
        return {"ok": 1}


def build_client(**overrides: Any) -> Iterator[TestClient]:
    base: dict[str, Any] = {
        "jwt_secret_key": SecretStr("test-secret-key-for-api-tests-long-enough"),
    }
    base.update(overrides)
    config = Settings(**base)
    with TestClient(create_app(config=config, database=FakeDatabase())) as client:
        yield client


@pytest.fixture
def unconfigured_client() -> Iterator[TestClient]:
    yield from build_client()


@pytest.fixture
def configured_client() -> Iterator[TestClient]:
    yield from build_client(
        cloudinary_cloud_name="demo-cloud",
        cloudinary_api_key="demo-key",
        cloudinary_api_secret=SecretStr("demo-secret"),
        cloudinary_max_upload_bytes=8,
    )


def register_and_login(client: TestClient, email: str) -> str:
    client.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-123"})
    response = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "correct-horse-123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_media_upload_requires_cloudinary_credentials(unconfigured_client: TestClient) -> None:
    token = register_and_login(unconfigured_client, "nocreds@example.com")
    response = unconfigured_client.post(
        "/api/v1/emotions",
        data={"label": "happy"},
        files={"media_file": ("emotion.jpg", b"abc", "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Media upload is not configured"


def test_emotion_without_media_works_without_cloudinary(unconfigured_client: TestClient) -> None:
    token = register_and_login(unconfigured_client, "plain@example.com")
    response = unconfigured_client.post(
        "/api/v1/emotions",
        data={"label": "calm"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    assert response.json()["media_url"] is None


def test_media_rejects_unsupported_format(configured_client: TestClient) -> None:
    token = register_and_login(configured_client, "format@example.com")
    response = configured_client.post(
        "/api/v1/emotions",
        data={"label": "happy"},
        files={"media_file": ("notes.txt", b"abc", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 415
    assert response.json()["detail"] == "Unsupported media format"


def test_media_rejects_oversized_file(configured_client: TestClient) -> None:
    token = register_and_login(configured_client, "size@example.com")
    response = configured_client.post(
        "/api/v1/emotions",
        data={"label": "happy"},
        files={"media_file": ("emotion.jpg", b"123456789", "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "Media file exceeds the configured size limit"


def test_media_upload_stores_cloudinary_metadata(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_upload(file: Any, **kwargs: Any) -> dict[str, str]:
        captured.update(kwargs)
        return {
            "secure_url": "https://res.cloudinary.com/demo-cloud/image/upload/emotion-media/emotion.jpg",
            "public_id": "emotion-media/emotion",
            "resource_type": "image",
        }

    monkeypatch.setattr(cloudinary.uploader, "upload", fake_upload)
    token = register_and_login(configured_client, "store@example.com")
    response = configured_client.post(
        "/api/v1/emotions",
        data={"label": "surprised"},
        files={"media_file": ("emotion.jpg", b"abc", "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["media_url"].startswith("https://res.cloudinary.com/demo-cloud/")

    stored = configured_client.app.state.database.emotions.documents[0]
    assert stored["media"]["public_id"] == "emotion-media/emotion"
    assert stored["media"]["resource_type"] == "image"
    assert captured["folder"] == "emotion-media"
    assert captured["cloud_name"] == "demo-cloud"
    assert captured["api_secret"] == "demo-secret"
    assert captured["allowed_formats"] == ["jpeg", "jpg", "mov", "mp4", "png", "webp"]


def test_deleting_emotion_cleans_up_cloudinary_media(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destroyed: list[tuple[str, str]] = []

    def fake_upload(*_: Any, **__: Any) -> dict[str, str]:
        return {
            "secure_url": "https://res.cloudinary.com/demo-cloud/image/upload/emotion-media/emotion.jpg",
            "public_id": "emotion-media/emotion",
            "resource_type": "image",
        }

    def fake_destroy(public_id: str, **kwargs: Any) -> dict[str, str]:
        destroyed.append((public_id, kwargs.get("resource_type", "")))
        return {"result": "ok"}

    monkeypatch.setattr(cloudinary.uploader, "upload", fake_upload)
    monkeypatch.setattr(cloudinary.uploader, "destroy", fake_destroy)
    token = register_and_login(configured_client, "cleanup@example.com")
    created = configured_client.post(
        "/api/v1/emotions",
        data={"label": "sad"},
        files={"media_file": ("emotion.jpg", b"abc", "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 201
    emotion_id = created.json()["id"]

    deleted = configured_client.delete(
        f"/api/v1/emotions/{emotion_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 204
    assert destroyed == [("emotion-media/emotion", "image")]
    assert configured_client.app.state.database.emotions.documents == []