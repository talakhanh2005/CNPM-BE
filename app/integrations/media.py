"""File-type checks and media results merged from BE A ``cloudinary_service``.

Content type and extension are client-declared; magic bytes are checked before any upload.
Errors keep BE A's codes but use the shared ``AppError`` envelope.
"""

import io
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.core.errors import AppError

# Content type (before ";") -> file format. MediaRecorder sends e.g. "audio/webm;codecs=opus".
CONTENT_TYPE_FORMATS: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "audio/webm": "webm",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/vnd.wave": "wav",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/msword": "doc",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.ms-excel": "xls",
}

# Extension -> content type, used only when the client sends a generic content type.
EXTENSION_CONTENT_TYPES: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "doc": "application/msword",
    "ppt": "application/vnd.ms-powerpoint",
    "xls": "application/vnd.ms-excel",
}
GENERIC_CONTENT_TYPES = ("", "application/octet-stream")

# Format -> magic-byte family. "zip:<folder>" means a ZIP that contains that root folder.
MAGIC_FAMILIES: dict[str, str] = {
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "png": "png",
    "webp": "webp",
    "webm": "ebml",
    "mp4": "isobmff",
    "mov": "isobmff",
    "m4a": "isobmff",
    "mp3": "mp3",
    "wav": "wav",
    "ogg": "ogg",
    "pdf": "pdf",
    "docx": "zip:word",
    "pptx": "zip:ppt",
    "xlsx": "zip:xl",
    "doc": "ole",
    "ppt": "ole",
    "xls": "ole",
}
IMAGE_FORMATS = ("jpg", "jpeg", "png", "webp")
DOCUMENT_FORMATS = ("pdf", "docx", "pptx", "xlsx", "doc", "ppt", "xls")
SIGNED_RESOURCE_TYPES = ("image", "video", "raw", "auto")
# Cloudinary rejects signatures whose timestamp is older than one hour.
MAX_SIGNATURE_AGE_SECONDS = 3600


def file_too_large():
    return AppError(413, "FILE_TOO_LARGE", "File vượt quá dung lượng cho phép.")


def unsupported_media(message="Định dạng file không được hỗ trợ."):
    return AppError(415, "UNSUPPORTED_MEDIA_TYPE", message)


def upload_failed(message="Không thể xử lý file trên dịch vụ lưu trữ."):
    return AppError(502, "UPLOAD_FAILED", message)


def media_not_found():
    return AppError(404, "MEDIA_NOT_FOUND", "Không tìm thấy file.")


def media_not_configured():
    return AppError(503, "MEDIA_NOT_CONFIGURED", "Dịch vụ lưu trữ media chưa được cấu hình.")


async def read_upload(file, max_bytes: int) -> bytes:
    """Read a multipart UploadFile but never more than the limit into RAM; always closes it."""
    try:
        if file.size is not None and file.size > max_bytes:
            raise file_too_large()
        content = await file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise file_too_large()
        return content
    finally:
        await file.close()


def normalize_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def resolve_content_type(content_type: str | None, filename: str | None) -> str:
    """Trust a specific header; derive a generic one from the extension (magic bytes recheck)."""
    normalized = normalize_content_type(content_type)
    if normalized not in GENERIC_CONTENT_TYPES:
        return normalized
    extension = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return EXTENSION_CONTENT_TYPES.get(extension, normalized)


def detect_magic_family(content: bytes) -> str | None:
    head = content[:16]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "ebml"
    if head[4:8] == b"ftyp":
        return "isobmff"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


def zip_contains_folder(content: bytes, folder: str) -> bool:
    # Reads only the central directory, never extracts: not exposed to zip bombs.
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return any(name.startswith(f"{folder}/") for name in archive.namelist())
    except zipfile.BadZipFile:
        return False


def resource_type_for(media_format: str) -> str:
    if media_format in IMAGE_FORMATS:
        return "image"
    if media_format in DOCUMENT_FORMATS:
        return "raw"
    return "video"  # Cloudinary stores audio as video


def validate_format(
    content_type: str, size: int, max_bytes: int, allowed_formats: Iterable[str]
) -> str:
    if size > max_bytes:
        raise file_too_large()
    media_format = CONTENT_TYPE_FORMATS.get(normalize_content_type(content_type))
    allowed = set(allowed_formats)
    if "jpeg" in allowed:
        allowed.add("jpg")
    if media_format is None or media_format not in allowed:
        raise unsupported_media()
    return media_format


def validate_magic_bytes(content: bytes, content_type: str) -> None:
    media_format = CONTENT_TYPE_FORMATS.get(normalize_content_type(content_type))
    expected = MAGIC_FAMILIES.get(media_format or "")
    detected = detect_magic_family(content)
    if expected is not None and expected.startswith("zip:"):
        matches = detected == "zip" and zip_contains_folder(content, expected.removeprefix("zip:"))
    else:
        matches = expected is not None and detected == expected
    if not matches:
        raise unsupported_media("Nội dung file không khớp với định dạng khai báo.")


@dataclass
class MediaInfo:
    url: str
    public_id: str
    resource_type: str
    format: str | None
    bytes: int | None
    created_at: str | None
    width: int | None = None
    height: int | None = None
    duration: float | None = None

    @classmethod
    def from_cloudinary(cls, result: dict[str, Any]) -> "MediaInfo":
        return cls(
            url=result.get("secure_url") or result.get("url", ""),
            public_id=result["public_id"],
            resource_type=result.get("resource_type", "image"),
            format=result.get("format"),
            bytes=result.get("bytes"),
            created_at=result.get("created_at"),
            width=result.get("width"),
            height=result.get("height"),
            duration=result.get("duration"),
        )

    def to_api(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "public_id": self.public_id,
            "resource_type": self.resource_type,
            "format": self.format,
            "bytes": self.bytes,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "created_at": self.created_at,
        }
