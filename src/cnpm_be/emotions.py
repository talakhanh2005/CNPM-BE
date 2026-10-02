from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from cnpm_be.auth import get_current_user
from cnpm_be.cloudinary_service import delete_media, upload_media
from cnpm_be.database import get_database
from cnpm_be.schemas import EmotionRead

router = APIRouter(prefix="/api/v1/emotions", tags=["emotions"])


def serialize_emotion(document: dict[str, Any]) -> dict[str, Any]:
    media = document.get("media")
    return {
        "id": str(document["_id"]),
        "user_id": str(document["user_id"]),
        "label": document["label"],
        "created_at": document["created_at"],
        "media_url": media.get("url") if media else None,
    }


def parse_emotion_id(emotion_id: str) -> ObjectId:
    if not ObjectId.is_valid(emotion_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emotion not found")
    return ObjectId(emotion_id)


@router.post("", response_model=EmotionRead, status_code=status.HTTP_201_CREATED)
async def create_emotion(
    request: Request,
    label: str = Form(min_length=1, max_length=64),
    media_file: UploadFile | None = File(default=None),
    user: dict[str, Any] = Depends(get_current_user),
    database: Any = Depends(get_database),
) -> dict[str, Any]:
    label = label.strip()
    if not label:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Label cannot be blank")

    media = None
    if media_file is not None and media_file.filename:
        try:
            media = await upload_media(media_file, request.app.state.settings)
        finally:
            await media_file.close()

    emotion = {
        "user_id": user["_id"],
        "label": label,
        "created_at": datetime.now(UTC),
        "media": media,
    }
    try:
        result = await database.emotions.insert_one(emotion)
    except Exception:
        if media:
            try:
                await delete_media(media, request.app.state.settings)
            except HTTPException:
                pass
        raise
    emotion["_id"] = result.inserted_id
    return serialize_emotion(emotion)


@router.get("", response_model=list[EmotionRead])
async def list_emotions(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    user: dict[str, Any] = Depends(get_current_user),
    database: Any = Depends(get_database),
) -> list[dict[str, Any]]:
    cursor = (
        database.emotions.find({"user_id": user["_id"]})
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )
    return [serialize_emotion(emotion) async for emotion in cursor]


@router.get("/{emotion_id}", response_model=EmotionRead)
async def read_emotion(
    emotion_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    database: Any = Depends(get_database),
) -> dict[str, Any]:
    emotion = await database.emotions.find_one(
        {"_id": parse_emotion_id(emotion_id), "user_id": user["_id"]}
    )
    if emotion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emotion not found")
    return serialize_emotion(emotion)


@router.delete("/{emotion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_emotion(
    emotion_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    database: Any = Depends(get_database),
) -> None:
    emotion = await database.emotions.find_one(
        {"_id": parse_emotion_id(emotion_id), "user_id": user["_id"]}
    )
    if emotion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Emotion not found")
    if emotion.get("media"):
        await delete_media(emotion["media"], request.app.state.settings)
    await database.emotions.delete_one({"_id": emotion["_id"], "user_id": user["_id"]})