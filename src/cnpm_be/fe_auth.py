"""Classroom authentication endpoints matching the frontend contract.

The frontend logs in with ``username``/``role`` (teacher or student) and expects
``data.user`` in the register response and ``data.token`` + ``data.user`` in the
login response.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pymongo.errors import DuplicateKeyError

from cnpm_be.auth import create_access_token
from cnpm_be.database import get_database, password_hash
from cnpm_be.fe_common import (
    USER_ROLES,
    envelope_fail,
    envelope_ok,
    read_json_body,
    serialize_public_user,
)

router = APIRouter(prefix="/api/auth", tags=["classroom-auth"])


@router.post("/register")
async def register_account(
    request: Request,
    database: Any = Depends(get_database),
):
    body = await read_json_body(request)
    username = body.get("username")
    password = body.get("password")
    role = body.get("role")
    normalized_username = username.strip() if isinstance(username, str) else ""

    if (
        len(normalized_username) < 3
        or not isinstance(password, str)
        or len(password) < 4
        or role not in USER_ROLES
    ):
        return envelope_fail(
            "Tên đăng nhập, mật khẩu hoặc vai trò không hợp lệ.",
            422,
            "VALIDATION_ERROR",
        )

    if await database.accounts.find_one({"username_lower": normalized_username.lower()}):
        return envelope_fail("Tên đăng nhập đã tồn tại.", 409, "USERNAME_TAKEN")

    document = {
        "username": normalized_username,
        "username_lower": normalized_username.lower(),
        "password_hash": password_hash.hash(password),
        "role": role,
    }
    try:
        result = await database.accounts.insert_one(document)
    except DuplicateKeyError:
        return envelope_fail("Tên đăng nhập đã tồn tại.", 409, "USERNAME_TAKEN")

    document["_id"] = result.inserted_id
    return envelope_ok({"user": serialize_public_user(document)}, "Đăng ký thành công.")


@router.post("/login")
async def login_account(
    request: Request,
    database: Any = Depends(get_database),
):
    body = await read_json_body(request)
    username = body.get("username")
    password = body.get("password")
    role = body.get("role")
    normalized_username = username.strip().lower() if isinstance(username, str) else ""

    invalid = envelope_fail(
        "Tên đăng nhập, mật khẩu hoặc vai trò không đúng.",
        401,
        "INVALID_CREDENTIALS",
    )
    account = (
        await database.accounts.find_one({"username_lower": normalized_username})
        if normalized_username
        else None
    )
    if account is None or not isinstance(password, str) or account.get("role") != role:
        return invalid

    try:
        password_matches = password_hash.verify(password, account["password_hash"])
    except Exception:
        password_matches = False
    if not password_matches:
        return invalid

    token = create_access_token(str(account["_id"]), request)
    return envelope_ok(
        {"token": token, "user": serialize_public_user(account)},
        "Đăng nhập thành công.",
    )
