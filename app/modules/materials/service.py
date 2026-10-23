import secrets
from datetime import timedelta
from io import BytesIO
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile

from app.core.db import new_id, now
from app.core.errors import AppError
from app.core.mongo import model_from_doc
from app.integrations import media
from app.modules.materials.model import Material
from app.modules.meetings.service import MeetingService, as_utc

MIMES = {
    ".pdf": "application/pdf",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
    # Images were allowed by BE A documents.
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
# BE A multipart documents: Office/PDF plus images.
DOC_FORMATS = ("pdf", "pptx", "ppt", "docx", "doc", "xlsx", "xls", "png", "jpg", "jpeg")
DOCUMENT_FOLDER = "openemotion/docs"
DOWNLOAD_URL_TTL_SECONDS = 300
DEFAULT_SHARE_HOURS = 24
MAX_SHARE_HOURS = 24 * 7
MAX_TAGS = 10
MAX_TAG_LENGTH = 30


def document_not_found():
    # Missing and forbidden look the same so document ids cannot be probed (BE A).
    return AppError(404, "DOCUMENT_NOT_FOUND", "Không tìm thấy")


def share_path(token):
    return f"/share/documents/{token}"


def parse_tags(raw):
    tags = list(dict.fromkeys(tag.strip() for tag in (raw or "").split(",") if tag.strip()))
    if len(tags) > MAX_TAGS or any(len(tag) > MAX_TAG_LENGTH for tag in tags):
        raise AppError(
            422,
            "VALIDATION_ERROR",
            f"Tối đa {MAX_TAGS} tag, mỗi tag tối đa {MAX_TAG_LENGTH} ký tự.",
        )
    return tags


def material_out(material, teacher_view):
    payload = {
        "id": material.id,
        "meeting_id": material.meeting_id,
        "uploaded_by": material.uploaded_by,
        "filename": material.filename,
        "content_type": material.content_type,
        "size_bytes": material.size_bytes,
        "created_at": material.created_at,
        "format": material.format,
        "tags": material.tags or [],
    }
    if teacher_view:
        payload.update(
            {
                "shared_with": material.shared_with or [],
                "shared_with_all": bool(material.shared_with_all),
                "revoked": material.revoked_at is not None,
                "revoked_at": material.revoked_at,
                "share_path": share_path(material.share_token) if material.share_token else None,
                "share_expires_at": material.share_expires_at,
            }
        )
    return payload


class MaterialService:
    def __init__(self, db, storage=None, settings=None):
        self.db, self.storage, self.settings = db, storage, settings
        self.meetings = MeetingService(db)

    # ------------------------------------------------------------------ queries

    def for_meeting(self, meeting_id):
        return [
            model_from_doc(Material, doc)
            for doc in self.db.collection("materials")
            .find({"meeting_id": meeting_id})
            .sort([("created_at", -1), ("id", -1)])
        ]

    def by_token(self, token):
        return model_from_doc(
            Material, self.db.collection("materials").find_one({"share_token": token})
        )

    def count(self, meeting_id):
        return len(self.for_meeting(meeting_id))

    # ------------------------------------------------------------------ access

    def can_access(self, meeting, material, user):
        """Owner always; members only for unrevoked material shared with all or with them."""
        if meeting.teacher_id == user.id:
            return True
        if self.meetings.repo.participant(meeting.id, user.id) is None:
            return False
        if material.revoked_at is not None:
            return False
        return bool(material.shared_with_all) or user.id in (material.shared_with or [])

    def owned(self, meeting_id, material_id, user):
        meeting = self.meetings.repo.get(meeting_id)
        if meeting is None or user.role != "teacher" or meeting.teacher_id != user.id:
            raise document_not_found()
        material = self.db.get(Material, material_id)
        if material is None or material.meeting_id != meeting_id:
            raise document_not_found()
        return meeting, material

    def viewable(self, meeting_id, user):
        """BE A can_view: host teacher or any participant; otherwise 404."""
        meeting = self.meetings.repo.get(meeting_id)
        if meeting is None:
            raise document_not_found()
        if meeting.teacher_id != user.id and (
            user.role == "teacher" or self.meetings.repo.participant(meeting_id, user.id) is None
        ):
            raise document_not_found()
        return meeting

    def visible_document(self, meeting_id, material_id, user):
        meeting = self.viewable(meeting_id, user)
        material = self.db.get(Material, material_id)
        if (
            material is None
            or material.meeting_id != meeting_id
            or not self.can_access(meeting, material, user)
        ):
            raise document_not_found()
        return meeting, material

    def check_limit(self, meeting_id):
        limit = self.settings.max_documents_per_meeting if self.settings else 100
        if self.count(meeting_id) >= limit:
            raise AppError(400, "DOCUMENT_LIMIT_REACHED", "Buổi học đã đạt số tài liệu tối đa.")

    def download_url(self, material):
        """Signed five-minute URL; the stored Cloudinary URL is never returned."""
        if material.resource_type == "image":
            url, _ = self.storage.private_url(
                material.public_id,
                resource_type="image",
                media_format=material.format or "",
                ttl=DOWNLOAD_URL_TTL_SECONDS,
            )
            return url
        return self.storage.document_download_url(material.public_id)

    def preview_url(self, material):
        """Signed inline URL for browser-safe presentation formats."""
        if material.resource_type == "image":
            return self.download_url(material)
        if material.content_type == "application/pdf" or (material.content_type or "").startswith(
            "image/"
        ):
            return self.storage.document_preview_url(material.public_id)
        return None

    # ------------------------------------------------------------------ BE B raw upload

    def validate(self, filename, content_type, data):
        if not filename or len(filename) > 255 or any(c in filename for c in "/\\\r\n\x00"):
            raise AppError(422, "INVALID_FILENAME", "Use a filename without path components")
        suffix = PurePath(filename).suffix.lower()
        if suffix not in MIMES or content_type != MIMES[suffix]:
            raise AppError(
                415, "UNSUPPORTED_DOCUMENT", "File extension and Content-Type must match"
            )
        if not data:
            raise AppError(422, "EMPTY_DOCUMENT", "Document body is empty")
        if len(data) > self.settings.max_document_bytes:
            raise AppError(413, "DOCUMENT_TOO_LARGE", "Document exceeds configured size limit")
        valid = False
        if suffix == ".pdf":
            valid = data.startswith(b"%PDF-")
        elif suffix in {".ppt", ".doc", ".xls"}:
            valid = data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        elif suffix == ".txt":
            try:
                data.decode("utf-8")
                valid = b"\x00" not in data
            except UnicodeDecodeError:
                pass
        elif suffix in {".png", ".jpg", ".jpeg"}:
            valid = media.detect_magic_family(data) == ("png" if suffix == ".png" else "jpeg")
        else:
            required = {
                ".pptx": "ppt/presentation.xml",
                ".docx": "word/document.xml",
                ".xlsx": "xl/workbook.xml",
            }[suffix]
            try:
                with ZipFile(BytesIO(data)) as archive:
                    entries = archive.infolist()
                    names = {entry.filename for entry in entries}
                    valid = (
                        required in names
                        and "[Content_Types].xml" in names
                        and len(entries) <= 10000
                        and sum(entry.file_size for entry in entries) <= 200 * 1024 * 1024
                        and not any(name.lower().endswith("vbaproject.bin") for name in names)
                    )
            except BadZipFile:
                pass
        if not valid:
            raise AppError(415, "INVALID_DOCUMENT", "Document signature or container is invalid")
        return suffix

    def upload(self, meeting_id, user, filename, content_type, data):
        self.meetings.require(meeting_id, user, owner=True)
        suffix = self.validate(filename, content_type, data)
        self.check_limit(meeting_id)
        material_id = new_id()
        public_id = f"face-emotion/{meeting_id}/materials/{material_id}{suffix}"
        self.db.commit()
        self.storage.upload_document(data, public_id)
        try:
            material = Material(
                id=material_id,
                meeting_id=meeting_id,
                uploaded_by=user.id,
                filename=filename,
                content_type=content_type,
                size_bytes=len(data),
                public_id=public_id,
                created_at=now(),
                format=suffix.lstrip("."),
                resource_type="raw",
                tags=[],
                shared_with=[],
                shared_with_all=True,  # BE B: materials are visible to every member
                revoked_at=None,
                share_token=None,
                share_expires_at=None,
            )
            self.db.add(material)
            self.db.commit()
            return material
        except Exception:
            self.db.rollback()
            self.storage.delete_document(public_id)
            raise

    def list(self, meeting_id, user, offset, limit):
        meeting = self.meetings.require(meeting_id, user)
        visible = [m for m in self.for_meeting(meeting_id) if self.can_access(meeting, m, user)]
        return meeting, visible[offset : offset + limit]

    def require(self, material_id, user):
        material = self.db.get(Material, material_id)
        if not material:
            raise AppError(404, "MATERIAL_NOT_FOUND", "Material not found")
        meeting = self.meetings.require(material.meeting_id, user)
        if not self.can_access(meeting, material, user):
            raise AppError(404, "MATERIAL_NOT_FOUND", "Material not found")
        return material

    # ------------------------------------------------------------------ BE A documents

    def upload_document(self, meeting_id, user, filename, content_type, content, tags):
        meeting = self.meetings.repo.get(meeting_id)
        if meeting is None or user.role != "teacher" or meeting.teacher_id != user.id:
            raise document_not_found()
        self.check_limit(meeting_id)
        document_id = new_id()
        media_format = media.validate_format(
            content_type, len(content), self.settings.max_document_bytes, DOC_FORMATS
        )
        info = self.storage.upload_media(
            content,
            content_type=content_type,
            folder=f"{DOCUMENT_FOLDER}/{meeting_id}",
            # Raw files keep their extension so downloads open with the right name.
            public_id=document_id
            if media_format in media.IMAGE_FORMATS
            else f"{document_id}.{media_format}",
            allowed_formats=DOC_FORMATS,
            max_bytes=self.settings.max_document_bytes,
            delivery_type="authenticated",
        )
        try:
            material = Material(
                id=document_id,
                meeting_id=meeting_id,
                uploaded_by=user.id,
                filename=PurePath(filename).name[:255],
                content_type=content_type,
                size_bytes=len(content),
                public_id=info.public_id,
                created_at=now(),
                format=media_format,
                resource_type=info.resource_type,
                tags=tags,
                shared_with=[],
                shared_with_all=False,  # BE A: private until the teacher shares it
                revoked_at=None,
                share_token=None,
                share_expires_at=None,
            )
            self.db.add(material)
            self.db.commit()
            return material
        except Exception:
            self.db.rollback()
            self.storage.delete_media(info.public_id, info.resource_type, "authenticated")
            raise

    def delete(self, meeting_id, material_id, user):
        _, material = self.owned(meeting_id, material_id, user)
        # Delete the file first; on storage failure keep the row so the file is not lost.
        self.storage.delete_media(
            material.public_id, material.resource_type or "raw", "authenticated"
        )
        self.db.collection("materials").delete_one({"id": material.id})

    def account_ids(self, meeting, ids):
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise AppError(422, "VALIDATION_ERROR", "account_ids phải là mảng chuỗi.")
        members = {p.user_id for p in meeting.participants}
        if any(item not in members for item in ids):
            raise AppError(
                422, "VALIDATION_ERROR", "Có account_ids không phải thành viên buổi học."
            )
        return list(dict.fromkeys(ids))

    def share(self, meeting_id, material_id, user, ids):
        meeting, material = self.owned(meeting_id, material_id, user)
        ids = self.account_ids(meeting, ids)
        if ids:  # [] shares with the whole class
            material.shared_with_all = False
            material.shared_with = list(dict.fromkeys([*(material.shared_with or []), *ids]))
        else:
            material.shared_with_all = True
        self.db.commit()
        return material

    def unshare(self, meeting_id, material_id, user, ids):
        meeting, material = self.owned(meeting_id, material_id, user)
        ids = self.account_ids(meeting, ids)
        if ids:  # removes these ids only; shared_with_all is untouched
            material.shared_with = [i for i in material.shared_with or [] if i not in ids]
        else:
            material.shared_with_all, material.shared_with = False, []
        self.db.commit()
        return material

    def revoke(self, meeting_id, material_id, user):
        _, material = self.owned(meeting_id, material_id, user)
        material.revoked_at = material.revoked_at or now()  # keep the first revocation time
        self.db.commit()
        return material

    def restore(self, meeting_id, material_id, user):
        _, material = self.owned(meeting_id, material_id, user)
        material.revoked_at = None
        self.db.commit()
        return material

    def generate_share_link(self, meeting_id, material_id, user, hours):
        _, material = self.owned(meeting_id, material_id, user)
        if material.revoked_at is not None:
            raise AppError(
                409,
                "DOCUMENT_REVOKED",
                "Tài liệu đang bị thu hồi; khôi phục trước khi tạo link.",
            )
        if (
            isinstance(hours, bool)
            or not isinstance(hours, int)
            or not 1 <= hours <= MAX_SHARE_HOURS
        ):
            raise AppError(
                422, "VALIDATION_ERROR", f"expires_in_hours phải trong khoảng 1-{MAX_SHARE_HOURS}."
            )
        # 256-bit random lookup key, not a JWT: replacing or revoking it takes effect at once.
        material.share_token = secrets.token_urlsafe(32)
        material.share_expires_at = now() + timedelta(hours=hours)
        self.db.commit()
        return material

    def shared(self, token):
        material = self.by_token(token)
        if material is None or self.meetings.repo.get(material.meeting_id) is None:
            raise document_not_found()
        expires = material.share_expires_at
        if material.revoked_at is not None or expires is None or as_utc(expires) <= now():
            raise AppError(410, "SHARE_LINK_GONE", "Link chia sẻ đã bị thu hồi hoặc hết hạn.")
        return material

    def filtered(self, meeting, user, q, tag, start, end, include_revoked):
        teacher_view = meeting.teacher_id == user.id
        needle = (q or "").strip().casefold()
        items = []
        for material in self.for_meeting(meeting.id):
            if teacher_view:
                if not include_revoked and material.revoked_at is not None:
                    continue
            elif not self.can_access(meeting, material, user):
                continue
            created = as_utc(material.created_at)
            if needle and needle not in material.filename.casefold():
                continue
            if tag and tag not in (material.tags or []):
                continue
            if start is not None and created < start[0]:
                continue
            if end is not None:
                end_value, date_only = end
                if created >= end_value + timedelta(days=1) if date_only else created > end_value:
                    continue
            items.append(material)
        return teacher_view, items
