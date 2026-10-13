"""BE A /api/v1/emotions: a user's own manual emotion labels with optional media.

Realtime classroom emotion (frames + AI) lives in app/modules/emotions.
"""

import logging

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.db import new_id, now
from app.core.dependencies import DB, CurrentUser
from app.core.errors import AppError
from app.core.mongo import model_from_doc
from app.core.schemas import ok
from app.integrations.media import read_upload, resolve_content_type
from app.modules.emotion_labels.model import EmotionLabel

router = APIRouter(prefix="/v1/emotions", tags=["v1 Emotion labels (BE A)"])
logger = logging.getLogger(__name__)


def label_out(label):
    return {
        "id": label.id,
        "user_id": label.user_id,
        "label": label.label,
        "created_at": label.created_at,
        "media_url": label.media_url,
    }


def owned(db, emotion_id, user):
    label = db.get(EmotionLabel, emotion_id)
    if label is None or label.user_id != user.id:
        raise AppError(404, "EMOTION_NOT_FOUND", "Emotion not found")
    return label


@router.post("", status_code=201)
async def create_emotion(
    request: Request,
    user: CurrentUser,
    db: DB,
    label: str = Form(min_length=1, max_length=64),
    media_file: UploadFile | None = File(default=None),
):
    label = label.strip()
    if not label:
        raise AppError(422, "VALIDATION_ERROR", "Label cannot be blank")
    storage, settings = request.app.state.storage, request.app.state.settings
    info = None
    if media_file is not None and media_file.filename:
        filename, declared = media_file.filename, media_file.content_type
        content = await read_upload(media_file, settings.cloudinary_max_upload_bytes)
        info = await run_in_threadpool(
            lambda: storage.upload_media(
                content,
                content_type=resolve_content_type(declared, filename),
                folder=settings.cloudinary_folder,
            )
        )

    def save():
        record = EmotionLabel(
            id=new_id(),
            user_id=user.id,
            label=label,
            created_at=now(),
            media_url=info.url if info else None,
            media_public_id=info.public_id if info else None,
            media_resource_type=info.resource_type if info else None,
        )
        db.add(record)
        db.commit()
        return record

    try:
        record = await run_in_threadpool(save)
    except Exception:
        if info:
            try:
                await run_in_threadpool(storage.delete_media, info.public_id, info.resource_type)
            except AppError:
                logger.warning("Cloudinary cleanup required for %s", info.public_id)
        raise
    return ok(label_out(record), "Emotion created")


@router.get("")
def list_emotions(
    user: CurrentUser,
    db: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    if getattr(db, "is_mongo", False):
        labels = [
            model_from_doc(EmotionLabel, doc)
            for doc in db.collection("emotion_labels")
            .find({"user_id": user.id})
            .sort([("created_at", -1), ("id", -1)])
            .skip(offset)
            .limit(limit)
        ]
    else:
        labels = db.scalars(
            select(EmotionLabel)
            .where(EmotionLabel.user_id == user.id)
            .order_by(EmotionLabel.created_at.desc(), EmotionLabel.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    return ok([label_out(label) for label in labels])


@router.get("/{emotion_id}")
def read_emotion(emotion_id: str, user: CurrentUser, db: DB):
    return ok(label_out(owned(db, emotion_id, user)))


@router.delete("/{emotion_id}")
def delete_emotion(emotion_id: str, request: Request, user: CurrentUser, db: DB):
    """Media is removed first; if that fails the label is kept (BE A rule)."""
    label = owned(db, emotion_id, user)
    if label.media_public_id:
        request.app.state.storage.delete_media(
            label.media_public_id, label.media_resource_type or "image"
        )
    if getattr(db, "is_mongo", False):
        db.collection("emotion_labels").delete_one({"id": label.id})
    else:
        db.delete(label)
        db.commit()
    return ok({"id": emotion_id, "deleted": True}, "Emotion deleted")
