import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Protocol

import cloudinary
import cloudinary.api
import cloudinary.exceptions
import cloudinary.uploader
import cloudinary.utils

from app.core.errors import AppError
from app.integrations import media


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

    def upload_document(self, data, public_id):
        self.require_config()
        try:
            return cloudinary.uploader.upload(
                BytesIO(data),
                public_id=public_id,
                resource_type="raw",
                type="authenticated",
                overwrite=False,
                timeout=self.settings.upload_timeout_seconds,
                **self.options,
            )
        except Exception as exc:
            self.delete_document(public_id)
            raise AppError(
                502, "STORAGE_UPLOAD_FAILED", "Document upload failed or timed out"
            ) from exc

    def delete_document(self, public_id):
        try:
            cloudinary.uploader.destroy(
                public_id,
                resource_type="raw",
                type="authenticated",
                timeout=self.settings.upload_timeout_seconds,
                **self.options,
            )
        except Exception:
            logging.getLogger(__name__).error("Cloudinary document cleanup required: %s", public_id)

    def document_download_url(self, public_id, expires_in=300):
        self.require_config()
        return cloudinary.utils.private_download_url(
            public_id,
            "",
            resource_type="raw",
            type="authenticated",
            attachment=True,
            expires_at=int(time.time()) + expires_in,
            **self.options,
        )

    def document_preview_url(self, public_id, expires_in=300):
        """Short-lived inline URL for authenticated PDF presentation."""
        self.require_config()
        return cloudinary.utils.private_download_url(
            public_id,
            "",
            resource_type="raw",
            type="authenticated",
            attachment=False,
            expires_at=int(time.time()) + expires_in,
            **self.options,
        )

    # ------------------------------------------------------------------
    # Generic media merged from BE A (images, audio, video, documents).
    # ------------------------------------------------------------------

    def media_credentials(self):
        if not all(self.options.values()):
            raise media.media_not_configured()
        return self.options

    def upload_media(
        self,
        content,
        *,
        content_type,
        folder,
        public_id=None,
        allowed_formats=None,
        max_bytes=None,
        delivery_type="upload",
    ):
        """Validate size, declared type and magic bytes, then upload. Returns MediaInfo."""
        credentials = self.media_credentials()
        media_format = media.validate_format(
            content_type,
            len(content),
            max_bytes or self.settings.cloudinary_max_upload_bytes,
            allowed_formats if allowed_formats is not None else self.settings.allowed_formats_list,
        )
        media.validate_magic_bytes(content, content_type)
        options = {
            "folder": folder,
            "resource_type": media.resource_type_for(media_format),
            "type": delivery_type,
            "overwrite": False,
            "unique_filename": public_id is None,
            "timeout": self.settings.cloudinary_upload_timeout,
            **credentials,
        }
        if public_id:
            options["public_id"] = public_id
        try:
            result = cloudinary.uploader.upload(BytesIO(content), **options)
        except Exception as exc:
            # Never log options: they contain the API secret.
            logging.getLogger(__name__).error("Cloudinary upload failed: %s", type(exc).__name__)
            raise media.upload_failed() from exc
        return media.MediaInfo.from_cloudinary(result)

    def media_info(self, public_id, resource_type):
        credentials = self.media_credentials()
        try:
            result = cloudinary.api.resource(public_id, resource_type=resource_type, **credentials)
        except cloudinary.exceptions.NotFound as exc:
            raise media.media_not_found() from exc
        except Exception as exc:
            logging.getLogger(__name__).error("Cloudinary lookup failed: %s", type(exc).__name__)
            raise media.upload_failed() from exc
        return media.MediaInfo.from_cloudinary(result)

    def delete_media(self, public_id, resource_type, delivery_type="upload"):
        """True when deleted, False when already gone; raises so callers keep their DB row."""
        credentials = self.media_credentials()
        try:
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type=resource_type,
                type=delivery_type,
                invalidate=True,
                **credentials,
            )
        except Exception as exc:
            logging.getLogger(__name__).error("Cloudinary deletion failed: %s", type(exc).__name__)
            raise media.upload_failed("Không xoá được file trên dịch vụ lưu trữ.") from exc
        outcome = result.get("result")
        if outcome == "ok":
            return True
        if outcome == "not found":
            return False
        raise media.upload_failed("Không xoá được file trên dịch vụ lưu trữ.")

    def private_url(
        self, public_id, *, resource_type, media_format="", delivery_type="authenticated", ttl=300
    ):
        """Short-lived signed download URL; returns (url, unix expires_at)."""
        credentials = self.media_credentials()
        expires_at = int(time.time()) + ttl
        url = cloudinary.utils.private_download_url(
            public_id,
            media_format,
            resource_type=resource_type,
            type=delivery_type,
            expires_at=expires_at,
            **credentials,
        )
        return url, expires_at

    def signed_upload(
        self, *, folder, resource_type="auto", max_bytes=None, allowed_formats=None, expires_in=600
    ):
        """Parameters the browser sends straight to Cloudinary; the secret never leaves BE."""
        credentials = self.media_credentials()
        permitted = self.settings.allowed_formats_list
        formats = [item.lower() for item in (allowed_formats or permitted)]
        if any(item not in permitted for item in formats):
            raise media.unsupported_media()
        timestamp = int(time.time())
        params = {
            "timestamp": timestamp,
            "folder": folder,
            "allowed_formats": ",".join(formats),
            "unique_filename": "true",
            "overwrite": "false",
        }
        signature = cloudinary.utils.api_sign_request(params, credentials["api_secret"])
        lifetime = max(1, min(expires_in, media.MAX_SIGNATURE_AGE_SECONDS))
        limit = self.settings.cloudinary_max_upload_bytes
        return {
            "signature": signature,
            "timestamp": timestamp,
            "api_key": credentials["api_key"],
            "cloud_name": credentials["cloud_name"],
            "folder": folder,
            "upload_url": (
                f"https://api.cloudinary.com/v1_1/{credentials['cloud_name']}/{resource_type}/upload"
            ),
            "allowed_formats": params["allowed_formats"],
            "max_file_size": min(max_bytes or limit, limit),
            "expires_at": datetime.fromtimestamp(timestamp + lifetime, timezone.utc).isoformat(),
            "unique_filename": params["unique_filename"],
            "overwrite": params["overwrite"],
        }
