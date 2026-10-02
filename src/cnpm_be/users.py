from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.errors import DuplicateKeyError

from cnpm_be.auth import get_current_user, require_admin, serialize_user
from cnpm_be.database import get_database, password_hash
from cnpm_be.schemas import AdminUserUpdate, UserRead, UserUpdate

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def parse_user_id(user_id: str) -> ObjectId:
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return ObjectId(user_id)


def prepare_updates(updates: dict[str, Any]) -> dict[str, Any]:
    updates = {key: value for key, value in updates.items() if value is not None}
    if "email" in updates and updates["email"] is not None:
        updates["email"] = str(updates["email"]).lower()
    password = updates.pop("password", None)
    if password is not None:
        updates["password_hash"] = password_hash.hash(password)
    return updates


@router.get("/me", response_model=UserRead)
async def read_profile(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return serialize_user(user)


@router.put("/me", response_model=UserRead)
async def update_profile(
    user_update: UserUpdate,
    user: dict[str, Any] = Depends(get_current_user),
    database: Any = Depends(get_database),
) -> dict[str, Any]:
    updates = prepare_updates(user_update.model_dump(exclude_unset=True))
    if updates:
        try:
            await database.users.update_one({"_id": user["_id"]}, {"$set": updates})
        except DuplicateKeyError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered") from None
        user.update(updates)
    return serialize_user(user)


@router.get("", response_model=list[UserRead])
async def list_users(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    database: Any = Depends(get_database),
    _: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    cursor = database.users.find().sort("email", 1).skip(offset).limit(limit)
    return [serialize_user(user) async for user in cursor]


@router.get("/{user_id}", response_model=UserRead)
async def read_user(
    user_id: str,
    database: Any = Depends(get_database),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    user = await database.users.find_one({"_id": parse_user_id(user_id)})
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return serialize_user(user)


@router.put("/{user_id}", response_model=UserRead)
async def admin_update_user(
    user_id: str,
    user_update: AdminUserUpdate,
    database: Any = Depends(get_database),
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    object_id = parse_user_id(user_id)
    user = await database.users.find_one({"_id": object_id})
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updates = prepare_updates(user_update.model_dump(exclude_unset=True))
    if object_id == admin["_id"] and updates.get("role") == "user":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Admins cannot remove their own role")
    if updates:
        try:
            await database.users.update_one({"_id": object_id}, {"$set": updates})
        except DuplicateKeyError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered") from None
        user.update(updates)
    return serialize_user(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    admin: dict[str, Any] = Depends(require_admin),
    database: Any = Depends(get_database),
) -> None:
    object_id = parse_user_id(user_id)
    if admin["_id"] == object_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Admins cannot delete themselves")
    result = await database.users.delete_one({"_id": object_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")