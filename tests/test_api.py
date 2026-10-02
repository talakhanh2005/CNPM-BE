from collections.abc import AsyncIterator, Iterator
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pydantic import SecretStr

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
        document = next(
            (item for item in self.documents if self.matches(item, query)),
            None,
        )
        return deepcopy(document) if document is not None else None

    async def insert_one(self, document: dict[str, Any]) -> SimpleNamespace:
        stored = deepcopy(document)
        stored.setdefault("_id", ObjectId())
        self.documents.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        document = next(
            (item for item in self.documents if self.matches(item, query)),
            None,
        )
        if document is not None:
            document.update(update.get("$set", {}))

    async def delete_one(self, query: dict[str, Any]) -> SimpleNamespace:
        document = next(
            (item for item in self.documents if self.matches(item, query)),
            None,
        )
        if document is not None:
            self.documents.remove(document)
        return SimpleNamespace(deleted_count=int(document is not None))

    def find(self, query: dict[str, Any] | None = None) -> FakeCursor:
        query = query or {}
        return FakeCursor(
            [deepcopy(item) for item in self.documents if self.matches(item, query)]
        )


class FakeDatabase:
    def __init__(self) -> None:
        self.users = FakeCollection()
        self.emotions = FakeCollection()

    async def command(self, *_: Any, **__: Any) -> dict[str, int]:
        return {"ok": 1}


@pytest.fixture
def api_client() -> Iterator[TestClient]:
    config = Settings(jwt_secret_key=SecretStr("test-secret-key-for-api-tests-long-enough"))
    with TestClient(create_app(config=config, database=FakeDatabase())) as client:
        yield client


def register_and_login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-123", "display_name": "Test User"},
    )
    assert response.status_code == 201
    assert "password_hash" not in response.json()
    token_response = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "correct-horse-123"},
    )
    assert token_response.status_code == 200
    return token_response.json()["access_token"]


def test_register_login_profile_and_admin_guard(api_client: TestClient) -> None:
    token = register_and_login(api_client, "user@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    assert api_client.get("/api/v1/users/me", headers=headers).json()["email"] == "user@example.com"
    updated = api_client.put(
        "/api/v1/users/me",
        headers=headers,
        json={"display_name": "Updated Name"},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Updated Name"
    assert api_client.get("/api/v1/users").status_code == 401
    assert api_client.get("/api/v1/users", headers=headers).status_code == 403
    assert api_client.post(
        "/api/v1/auth/login",
        data={"username": "user@example.com", "password": "wrong-password"},
    ).status_code == 401
    assert api_client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "correct-horse-123"},
    ).status_code == 409


def test_admin_can_manage_users_but_not_delete_self(api_client: TestClient) -> None:
    admin_token = register_and_login(api_client, "admin@example.com")
    member_token = register_and_login(api_client, "member@example.com")
    database = api_client.app.state.database
    admin = next(user for user in database.users.documents if user["email"] == "admin@example.com")
    admin["role"] = "admin"
    member = next(user for user in database.users.documents if user["email"] == "member@example.com")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    assert len(api_client.get("/api/v1/users", headers=admin_headers).json()) == 2
    assert api_client.delete(f"/api/v1/users/{admin['_id']}", headers=admin_headers).status_code == 400
    assert api_client.put(
        f"/api/v1/users/{admin['_id']}",
        headers=admin_headers,
        json={"role": "user"},
    ).status_code == 400
    updated = api_client.put(
        f"/api/v1/users/{member['_id']}",
        headers=admin_headers,
        json={"display_name": "Updated by admin"},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Updated by admin"
    assert api_client.delete(f"/api/v1/users/{member['_id']}", headers=admin_headers).status_code == 204


def test_emotions_are_scoped_to_the_authenticated_user(api_client: TestClient) -> None:
    owner_token = register_and_login(api_client, "owner@example.com")
    other_token = register_and_login(api_client, "other@example.com")
    created = api_client.post(
        "/api/v1/emotions",
        data={"label": "happy"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert created.status_code == 201
    emotion_id = created.json()["id"]

    other_headers = {"Authorization": f"Bearer {other_token}"}
    assert api_client.get("/api/v1/emotions", headers=other_headers).json() == []
    assert api_client.get(f"/api/v1/emotions/{emotion_id}", headers=other_headers).status_code == 404


def test_optional_media_is_saved_as_cloudinary_metadata(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_upload(*_: Any, **__: Any) -> dict[str, str]:
        return {
            "url": "https://res.cloudinary.com/demo/image/upload/emotion.jpg",
            "public_id": "emotion-media/emotion",
            "resource_type": "image",
        }

    deleted_media: list[dict[str, Any]] = []

    async def fake_delete(media: dict[str, Any], *_: Any) -> None:
        deleted_media.append(media)

    monkeypatch.setattr("cnpm_be.emotions.upload_media", fake_upload)
    monkeypatch.setattr("cnpm_be.emotions.delete_media", fake_delete)
    token = register_and_login(api_client, "media@example.com")
    response = api_client.post(
        "/api/v1/emotions",
        data={"label": "calm"},
        files={"media_file": ("emotion.jpg", b"image-bytes", "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["media_url"].startswith("https://res.cloudinary.com/")
    emotion_id = response.json()["id"]
    deleted = api_client.delete(
        f"/api/v1/emotions/{emotion_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 204
    assert deleted_media[0]["public_id"] == "emotion-media/emotion"