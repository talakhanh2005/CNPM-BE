from io import BytesIO
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile

from sqlalchemy import select

from app.core.db import new_id, now
from app.core.errors import AppError
from app.core.mongo import model_from_doc
from app.modules.materials.model import Material
from app.modules.meetings.service import MeetingService

MIMES = {
    ".pdf": "application/pdf",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
}


class MaterialService:
    def __init__(self, db, storage=None, settings=None):
        self.db, self.storage, self.settings = db, storage, settings

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
        MeetingService(self.db).require(meeting_id, user, owner=True)
        suffix = self.validate(filename, content_type, data)
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
            )
            self.db.add(material)
            self.db.commit()
            return material
        except Exception:
            self.db.rollback()
            self.storage.delete_document(public_id)
            raise

    def list(self, meeting_id, user, offset, limit):
        MeetingService(self.db).require(meeting_id, user)
        if getattr(self.db, "is_mongo", False):
            return [
                model_from_doc(Material, doc)
                for doc in self.db.collection("materials")
                .find({"meeting_id": meeting_id})
                .sort([("created_at", -1), ("id", -1)])
                .skip(offset)
                .limit(limit)
            ]
        return self.db.scalars(
            select(Material)
            .where(Material.meeting_id == meeting_id)
            .order_by(Material.created_at.desc(), Material.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()

    def require(self, material_id, user):
        material = self.db.get(Material, material_id)
        if not material:
            raise AppError(404, "MATERIAL_NOT_FOUND", "Material not found")
        MeetingService(self.db).require(material.meeting_id, user)
        return material
