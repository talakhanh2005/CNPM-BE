import logging
from typing import Any

import cloudinary.uploader
from fastapi import HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from cnpm_be.config import Settings

logger = logging.getLogger(__name__)


def _credentials(config: Settings) -> dict[str, str]:
    if not all(
        (
            config.cloudinary_cloud_name,
            config.cloudinary_api_key,
            config.cloudinary_api_secret,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media upload is not configured",
        )
    return {
        "cloud_name": config.cloudinary_cloud_name,
        "api_key": config.cloudinary_api_key,
        "api_secret": config.cloudinary_api_secret.get_secret_value(),
    }


async def upload_media(file: UploadFile, config: Settings) -> dict[str, Any]:
    credentials = _credentials(config)
    extension = (file.filename or "").rsplit(".", 1)[-1].lower()
    allowed_formats = {item.lower() for item in config.cloudinary_allowed_formats}
    if extension not in allowed_formats:
        raise HTTPException(status_code=415, detail="Unsupported media format")

    content = await file.read(config.cloudinary_max_upload_bytes + 1)
    if len(content) > config.cloudinary_max_upload_bytes:
        raise HTTPException(status_code=413, detail="Media file exceeds the configured size limit")
    await file.seek(0)

    try:
        result = await run_in_threadpool(
            cloudinary.uploader.upload,
            file.file,
            folder=config.cloudinary_folder,
            resource_type="auto",
            allowed_formats=sorted(allowed_formats),
            secure=True,
            **credentials,
        )
    except Exception as error:
        logger.exception("Cloudinary media upload failed")
        raise HTTPException(status_code=502, detail="Media upload failed") from error

    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
        "resource_type": result.get("resource_type", "image"),
    }


async def delete_media(media: dict[str, Any], config: Settings) -> None:
    credentials = _credentials(config)
    try:
        result = await run_in_threadpool(
            cloudinary.uploader.destroy,
            media["public_id"],
            resource_type=media.get("resource_type", "image"),
            invalidate=True,
            **credentials,
        )
    except Exception as error:
        logger.exception("Cloudinary media deletion failed")
        raise HTTPException(status_code=502, detail="Media cleanup failed; emotion was not deleted") from error

    if result.get("result") not in {"ok", "not found"}:
        raise HTTPException(status_code=502, detail="Media cleanup failed; emotion was not deleted")