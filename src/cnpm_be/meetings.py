"""Classroom meeting endpoints matching the frontend contract."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request

from cnpm_be.database import get_database
from cnpm_be.fe_common import (
    build_ice_servers,
    envelope_fail,
    envelope_ok,
    find_room,
    get_current_account,
    has_turn_server,
    read_json_body,
    serialize_room,
    unauthorized,
)

router = APIRouter(prefix="/api/meetings", tags=["classroom-meetings"])

_background_tasks: set[asyncio.Task] = set()


async def _mark_recording_completed(database: Any, room_id: Any) -> None:
    await asyncio.sleep(4)
    await database.rooms.update_one({"_id": room_id}, {"$set": {"recording_status": "completed"}})


@router.get("/history")
async def meeting_history(
    account: dict[str, Any] | None = Depends(get_current_account),
    database: Any = Depends(get_database),
):
    if account is None:
        return unauthorized()
    user_id = str(account["_id"])
    cursor = database.rooms.find({"host_id": {"$in": [user_id, "teacher_sample"]}})
    rooms = [serialize_room(document) async for document in cursor]
    rooms.sort(key=lambda room: room["createdAt"] or "", reverse=True)
    return envelope_ok(rooms)


@router.post("/{room_id}/recording")
async def save_recording(
    room_id: str,
    request: Request,
    account: dict[str, Any] | None = Depends(get_current_account),
    database: Any = Depends(get_database),
):
    if account is None:
        return unauthorized()
    room = await find_room(database, room_id)
    if room is None:
        return envelope_fail("Không tìm thấy phòng.", 404, "ROOM_NOT_FOUND")

    body = await read_json_body(request)
    duration_seconds = body.get("durationSeconds")
    if not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool):
        duration_seconds = 60

    room["recording_status"] = "processing"
    room["duration_minutes"] = max(1, round(duration_seconds / 60))
    await database.rooms.update_one(
        {"_id": room["_id"]},
        {
            "$set": {
                "recording_status": room["recording_status"],
                "duration_minutes": room["duration_minutes"],
            }
        },
    )
    task = asyncio.create_task(_mark_recording_completed(database, room["_id"]))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return envelope_ok(serialize_room(room), "Bản ghi đã lưu, AI đang phân tích trong nền.")


@router.get("/{room_id}/ice-config")
async def ice_config(
    room_id: str,
    request: Request,
    account: dict[str, Any] | None = Depends(get_current_account),
    database: Any = Depends(get_database),
):
    if account is None:
        return unauthorized()
    room = await find_room(database, room_id)
    if room is None or room.get("status") != "active":
        return envelope_fail("Không tìm thấy phòng đang hoạt động.", 404, "ROOM_NOT_FOUND")

    user_id = str(account["_id"])
    participants = room.get("participants") or []
    joined = any(
        item["id"] == user_id and item.get("status") == "joined" for item in participants
    )
    if not joined:
        return envelope_fail("Bạn chưa tham gia phòng này.", 403, "NOT_A_PARTICIPANT")

    ice_servers = build_ice_servers(request.app.state.settings)
    return envelope_ok(
        {"iceServers": ice_servers, "turn_configured": has_turn_server(ice_servers)}
    )
