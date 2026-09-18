import logging
import math
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

import cloudinary
import cloudinary.uploader
import cloudinary.utils

from app.core.errors import AppError


@dataclass
class UploadedVideo:
    public_id: str
    url: str
    duration: float
    size_bytes: int
    format: str


class VideoStorage(Protocol):
    def upload(self, data: bytes, public_id: str) -> UploadedVideo: ...
    def delete(self, public_id: str) -> None: ...
    def download_url(self, public_id: str, format: str, expires_in: int = 300) -> str: ...


class CloudinaryStorage:
    """Authenticated Cloudinary assets; payloads stay in RAM, never spool to disk."""

    def __init__(self, settings):
        self.settings = settings
        self.options = dict(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
        )

    def require_config(self):
        if not all(self.options.values()):
            raise AppError(
                503, "STORAGE_NOT_CONFIGURED", "Cloudinary credentials are not configured"
            )

    def upload(self, data, public_id):
        self.require_config()
        try:
            result = cloudinary.uploader.upload(
                BytesIO(data),
                public_id=public_id,
                resource_type="video",
                type="authenticated",
                overwrite=False,
                timeout=self.settings.upload_timeout_seconds,
                **self.options,
            )
            duration = float(result.get("duration", 0))
            if (
                not math.isfinite(duration)
                or duration <= 0
                or result.get("format") not in {"mp4", "webm", "mov"}
            ):
                raise AppError(415, "INVALID_VIDEO", "Cloudinary could not validate this video")
            return UploadedVideo(
                result["public_id"],
                result["secure_url"],
                duration,
                int(result["bytes"]),
                result["format"],
            )
        except AppError:
            self.delete(public_id)
            raise
        except Exception as exc:
            # Timeout can be ambiguous: compensate using the preallocated asset id.
            self.delete(public_id)
            logging.getLogger(__name__).warning("Cloudinary upload failed: %s", type(exc).__name__)
            raise AppError(
                502, "STORAGE_UPLOAD_FAILED", "Cloudinary upload failed or timed out"
            ) from exc

    def delete(self, public_id):
        try:
            cloudinary.uploader.destroy(
                public_id,
                resource_type="video",
                type="authenticated",
                invalidate=True,
                timeout=self.settings.upload_timeout_seconds,
                **self.options,
            )
        except Exception:
            logging.getLogger(__name__).error("Cloudinary cleanup required for asset %s", public_id)

    def download_url(self, public_id, format, expires_in=300):
        self.require_config()
        return cloudinary.utils.private_download_url(
            public_id,
            format,
            resource_type="video",
            type="authenticated",
            expires_at=int(time.time()) + expires_in,
            **self.options,
        )
