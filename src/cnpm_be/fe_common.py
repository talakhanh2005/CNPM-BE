"""Shared helpers for the classroom API consumed by the frontend.

The frontend expects every response wrapped in ``{success, data, message}`` and
uses camelCase field names, so the serializers here translate the snake_case
MongoDB documents into that contract.
"""

from datetime import UTC, datetime
from typing import Any

import jwt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer

from cnpm_be.database import get_database

USER_ROLES = ("teacher", "student")
PARTICIPANT_MODES = ("free", "approval")
ANALYSIS_MODES = ("realtime", "batch")

DEFAULT_STUN_URLS = ("stun:stun.l.google.com:19302",)

fe_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def envelope_ok(data: Any = None, message: str = "OK") -> JSONResponse:
    return JSONResponse({"success": True, "data": data, "message": message})


def envelope_fail(message: str, status_code: int = 400, code: str = "BAD_REQUEST") -> JSONResponse:
    return JSONResponse(
        {"success": False, "data": {"code": code}, "message": message},
        status_code=status_code,
    )


def unauthorized() -> JSONResponse:
    return envelope_fail("Bạn cần đăng nhập trước.", 401, "UNAUTHORIZED")


async def read_json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def now() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def serialize_public_user(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(document["_id"]),
        "username": document["username"],
        "role": document["role"],
    }


def serialize_participant(participant: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": participant["id"],
        "username": participant["username"],
        "role": participant["role"],
        "status": participant["status"],
        "joinedAt": to_iso(participant.get("joined_at")),
        "leftAt": to_iso(participant.get("left_at")),
    }
    if "disconnected_at" in participant:
        payload["disconnectedAt"] = to_iso(participant.get("disconnected_at"))
    return payload


def serialize_room(document: dict[str, Any]) -> dict[str, Any]:
    emotion_recognition = document.get("emotion_recognition", True)
    analysis_mode = document.get("analysis_mode") or (
        "realtime" if emotion_recognition else "batch"
    )
    return {
        "id": str(document["_id"]),
        "name": document.get("name") or "Lớp học trực tuyến",
        "code": document["code"],
        "hostId": document["host_id"],
        "status": document["status"],
        "participantMode": document["participant_mode"],
        "emotionRecognition": emotion_recognition,
        "analysisMode": analysis_mode,
        "recordingStatus": document.get("recording_status", "none"),
        "durationMinutes": document.get("duration_minutes", 45),
        "createdAt": to_iso(document["created_at"]),
        "participants": [
            serialize_participant(participant)
            for participant in document.get("participants", [])
        ],
    }


async def find_room(database: Any, room_id: str) -> dict[str, Any] | None:
    try:
        object_id = ObjectId(room_id)
    except (InvalidId, TypeError):
        return None
    return await database.rooms.find_one({"_id": object_id})


def build_ice_servers(config: Any) -> list[dict[str, Any]]:
    stun_urls = list(config.stun_urls) or list(DEFAULT_STUN_URLS)
    servers: list[dict[str, Any]] = [{"urls": stun_urls}]

    turn_credential = config.turn_credential.get_secret_value() if config.turn_credential else ""
    if config.turn_urls and config.turn_username and turn_credential:
        servers.append(
            {
                "urls": list(config.turn_urls),
                "username": config.turn_username,
                "credential": turn_credential,
            }
        )
    return servers


def has_turn_server(servers: list[dict[str, Any]]) -> bool:
    return any(
        url.startswith("turn")
        for server in servers
        for url in (server["urls"] if isinstance(server["urls"], list) else [server["urls"]])
    )


async def get_current_account(
    request: Request,
    token: str | None = Depends(fe_oauth2_scheme),
    database: Any = Depends(get_database),
) -> dict[str, Any] | None:
    if not token:
        return None
    config = request.app.state.settings
    try:
        payload = jwt.decode(
            token,
            config.jwt_secret_key.get_secret_value(),
            algorithms=[config.jwt_algorithm],
        )
        user_id = ObjectId(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None
    return await database.accounts.find_one({"_id": user_id})
