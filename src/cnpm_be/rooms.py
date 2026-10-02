"""Classroom room endpoints matching the frontend contract."""

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request

from cnpm_be.database import get_database
from cnpm_be.fe_common import (
    ANALYSIS_MODES,
    PARTICIPANT_MODES,
    envelope_fail,
    envelope_ok,
    find_room,
    get_current_account,
    now,
    read_json_body,
    serialize_room,
    to_iso,
    unauthorized,
)

router = APIRouter(prefix="/api/rooms", tags=["classroom-rooms"])

CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


async def generate_room_code(database: Any) -> str:
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if await database.rooms.find_one({"code": code}) is None:
            return code


@router.post("")
async def create_room(
    request: Request,
    account: dict[str, Any] | None = Depends(get_current_account),
    database: Any = Depends(get_database),
):
    if account is None:
        return unauthorized()
    if account.get("role") != "teacher":
        return envelope_fail("Chỉ giáo viên có thể tạo phòng.", 403, "FORBIDDEN")

    body = await read_json_body(request)
    participant_mode = body.get("participantMode")
    if participant_mode not in PARTICIPANT_MODES:
        return envelope_fail("Thiết lập phòng không hợp lệ.", 422, "VALIDATION_ERROR")

    name = body.get("name")
    name = name.strip() if isinstance(name, str) and name.strip() else "Lớp học trực tuyến"
    analysis_mode = body.get("analysisMode")
    emotion_recognition = bool(body.get("emotionRecognition"))
    mode = (
        analysis_mode
        if analysis_mode in ANALYSIS_MODES
        else ("realtime" if emotion_recognition else "batch")
    )

    created_at = now()
    user_id = str(account["_id"])
    document = {
        "name": name,
        "code": await generate_room_code(database),
        "host_id": user_id,
        "status": "active",
        "participant_mode": participant_mode,
        "emotion_recognition": mode == "realtime",
        "analysis_mode": mode,
        "recording_status": "none",
        "duration_minutes": 45,
        "created_at": created_at,
        "ended_at": None,
        "participants": [
            {
                "id": user_id,
                "username": account["username"],
                "role": account["role"],
                "status": "joined",
                "joined_at": created_at,
                "left_at": None,
            }
        ],
    }
    result = await database.rooms.insert_one(document)
    document["_id"] = result.inserted_id
    return envelope_ok(serialize_room(document), "Tạo phòng thành công.")


@router.post("/join")
async def join_room(
    request: Request,
    account: dict[str, Any] | None = Depends(get_current_account),
    database: Any = Depends(get_database),
):
    if account is None:
        return unauthorized()

    body = await read_json_body(request)
    code = body.get("code")
    code = code.strip().upper() if isinstance(code, str) else ""
    room = await database.rooms.find_one({"code": code})
    if room is None:
        return envelope_fail("Không tìm thấy phòng với mã này.", 404, "ROOM_NOT_FOUND")
    if room.get("status") != "active":
        return envelope_fail("Phòng đã kết thúc.", 409, "ROOM_CLOSED")

    user_id = str(account["_id"])
    participants = room.get("participants") or []
    participant = next((item for item in participants if item["id"] == user_id), None)
    if participant is not None:
        participant["status"] = "joined"
        participant["joined_at"] = now()
        participant["left_at"] = None
        participant["disconnected_at"] = None
    else:
        participants.append(
            {
                "id": user_id,
                "username": account["username"],
                "role": account["role"],
                "status": "joined",
                "joined_at": now(),
                "left_at": None,
            }
        )
    room["participants"] = participants
    await database.rooms.update_one({"_id": room["_id"]}, {"$set": {"participants": participants}})
    return envelope_ok(serialize_room(room), "Tham gia phòng thành công.")


@router.get("/{room_id}")
async def get_room(
    room_id: str,
    account: dict[str, Any] | None = Depends(get_current_account),
    database: Any = Depends(get_database),
):
    if account is None:
        return unauthorized()
    room = await find_room(database, room_id)
    if room is None:
        return envelope_fail("Không tìm thấy phòng.", 404, "ROOM_NOT_FOUND")
    if room.get("status") != "active":
        return envelope_fail("Phòng đã kết thúc.", 409, "ROOM_CLOSED")

    user_id = str(account["_id"])
    participants = room.get("participants") or []
    participant = next((item for item in participants if item["id"] == user_id), None)
    if participant is None or participant.get("status") == "left":
        return envelope_fail("Bạn chưa tham gia phòng này.", 403, "NOT_A_PARTICIPANT")
    if participant.get("status") == "disconnected":
        participant["status"] = "joined"
        participant["joined_at"] = now()
        participant["disconnected_at"] = None
        room["participants"] = participants
        await database.rooms.update_one(
            {"_id": room["_id"]}, {"$set": {"participants": participants}}
        )
    return envelope_ok(serialize_room(room))


@router.post("/{room_id}/leave")
async def leave_room(
    room_id: str,
    account: dict[str, Any] | None = Depends(get_current_account),
    database: Any = Depends(get_database),
):
    if account is None:
        return unauthorized()
    room = await find_room(database, room_id)
    if room is None:
        return envelope_fail("Không tìm thấy phòng.", 404, "ROOM_NOT_FOUND")

    user_id = str(account["_id"])
    participants = room.get("participants") or []
    participant = next((item for item in participants if item["id"] == user_id), None)
    if participant is None:
        return envelope_fail("Bạn chưa tham gia phòng này.", 409, "NOT_A_PARTICIPANT")

    participant["status"] = "left"
    participant["left_at"] = now()
    await database.rooms.update_one({"_id": room["_id"]}, {"$set": {"participants": participants}})
    return envelope_ok(
        {
            "roomId": str(room["_id"]),
            "participantId": user_id,
            "status": participant["status"],
            "leftAt": to_iso(participant["left_at"]),
        },
        "Đã rời phòng.",
    )


@router.post("/{room_id}/end")
async def end_room(
    room_id: str,
    account: dict[str, Any] | None = Depends(get_current_account),
    database: Any = Depends(get_database),
):
    if account is None:
        return unauthorized()
    room = await find_room(database, room_id)
    if room is None:
        return envelope_fail("Không tìm thấy phòng.", 404, "ROOM_NOT_FOUND")

    user_id = str(account["_id"])
    if room.get("host_id") != user_id or account.get("role") != "teacher":
        return envelope_fail("Chỉ giáo viên tạo phòng mới có thể đóng phòng.", 403, "FORBIDDEN")
    if room.get("status") == "closed":
        return envelope_ok(serialize_room(room), "Phòng đã được đóng trước đó.")

    ended_at = now()
    participants = room.get("participants") or []
    for participant in participants:
        participant["status"] = "left"
        participant["left_at"] = participant.get("left_at") or ended_at
    room["status"] = "closed"
    room["ended_at"] = ended_at
    room["participants"] = participants
    await database.rooms.update_one(
        {"_id": room["_id"]},
        {"$set": {"status": "closed", "ended_at": ended_at, "participants": participants}},
    )
    return envelope_ok(serialize_room(room), "Đã đóng phòng học.")


@router.post("/{room_id}/disconnect")
async def disconnect_room(
    room_id: str,
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
    participant = next((item for item in participants if item["id"] == user_id), None)
    if participant is None or participant.get("status") == "left":
        return envelope_ok({"roomId": room_id, "status": "ignored"})

    participant["status"] = "disconnected"
    participant["disconnected_at"] = now()
    await database.rooms.update_one({"_id": room["_id"]}, {"$set": {"participants": participants}})
    return envelope_ok(
        {"roomId": str(room["_id"]), "participantId": user_id, "status": participant["status"]}
    )


