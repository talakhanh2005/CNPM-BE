import asyncio

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import DB, CurrentUser, Teacher
from app.core.errors import AppError
from app.core.query import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, paginate, parse_date, parse_int
from app.core.schemas import Envelope, ok
from app.integrations.media import read_upload, resolve_content_type
from app.modules.materials.schema import MaterialOut, ShareIn, ShareLinkIn
from app.modules.materials.service import (
    DOWNLOAD_URL_TTL_SECONDS,
    MIMES,
    MaterialService,
    material_out,
    parse_tags,
    share_path,
)
from app.modules.meetings.service import MeetingService
from app.modules.recordings.schema import PlaybackOut

router = APIRouter(tags=["Teaching materials"])
share_router = APIRouter(prefix="/share", tags=["Public share (BE A)"])


def no_store(payload, message="OK"):
    # Signed links live five minutes: browsers and proxies must not cache them.
    response = JSONResponse(jsonable_encoder(ok(payload, message)))
    response.headers["Cache-Control"] = "no-store"
    return response


# --------------------------------------------------------------------- BE B materials


@router.post(
    "/meetings/{meeting_id}/materials",
    status_code=201,
    response_model=Envelope[MaterialOut],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                mime: {"schema": {"type": "string", "format": "binary"}}
                for mime in set(MIMES.values())
            },
        }
    },
)
async def upload(
    meeting_id: str,
    request: Request,
    user: Teacher,
    db: DB,
    filename: str = Query(min_length=1, max_length=255),
):
    """Raw-body upload; visible to every member until the teacher changes sharing."""
    state = request.app.state
    await run_in_threadpool(MeetingService(db).require, meeting_id, user, True)
    await run_in_threadpool(db.commit)
    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in MIMES.values():
        raise AppError(415, "UNSUPPORTED_DOCUMENT", "Unsupported document Content-Type")
    if state.upload_semaphore.locked():
        raise AppError(429, "UPLOAD_BUSY", "Upload capacity reached; retry later")
    async with state.upload_semaphore:
        data = bytearray()
        try:
            async with asyncio.timeout(state.settings.upload_timeout_seconds):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > state.settings.max_document_bytes:
                        raise AppError(413, "DOCUMENT_TOO_LARGE", "Document exceeds size limit")
                    data.extend(chunk)
        except TimeoutError as exc:
            raise AppError(408, "UPLOAD_TIMEOUT", "Document stream timed out") from exc
        material = await run_in_threadpool(
            MaterialService(db, state.storage, state.settings).upload,
            meeting_id,
            user,
            filename,
            mime,
            bytes(data),
        )
        return ok(material_out(material, teacher_view=True), "Material uploaded")


@router.get("/meetings/{meeting_id}/materials", response_model=Envelope[list[MaterialOut]])
def list_materials(
    meeting_id: str,
    user: CurrentUser,
    db: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """Members see unrevoked material shared with them; the owner sees everything."""
    meeting, materials = MaterialService(db).list(meeting_id, user, offset, limit)
    teacher_view = meeting.teacher_id == user.id
    return ok([material_out(m, teacher_view) for m in materials])


@router.get("/materials/{material_id}/download", response_model=Envelope[PlaybackOut])
def download(material_id: str, request: Request, user: CurrentUser, db: DB):
    service = MaterialService(db, request.app.state.storage)
    material = service.require(material_id, user)
    return ok({"url": service.download_url(material), "expires_in": DOWNLOAD_URL_TTL_SECONDS})


# --------------------------------------------------------------------- BE A documents


@router.post("/meetings/{meeting_id}/documents", status_code=201)
async def upload_document(
    meeting_id: str,
    request: Request,
    user: CurrentUser,
    db: DB,
    file: UploadFile | None = File(default=None),
    tags: str | None = Form(default=None),
):
    """Multipart upload; private until shared. Returns metadata plus a 5-minute download URL."""
    state = request.app.state
    if file is None or not file.filename:
        raise AppError(422, "VALIDATION_ERROR", "Thiếu file tài liệu (field `file`).")
    tag_list = parse_tags(tags)
    filename, declared = file.filename, file.content_type
    content = await read_upload(file, state.settings.max_document_bytes)
    service = MaterialService(db, state.storage, state.settings)
    if state.upload_semaphore.locked():
        raise AppError(429, "UPLOAD_BUSY", "Upload capacity reached; retry later")
    async with state.upload_semaphore:
        material = await run_in_threadpool(
            service.upload_document,
            meeting_id,
            user,
            filename,
            resolve_content_type(declared, filename),
            content,
            tag_list,
        )
    url = await run_in_threadpool(service.download_url, material)
    return ok(
        {
            **material_out(material, teacher_view=True),
            "download_url": url,
            "expires_in": DOWNLOAD_URL_TTL_SECONDS,
        },
        "Đã tải tài liệu lên.",
    )


@router.get("/meetings/{meeting_id}/documents")
def list_documents(
    meeting_id: str,
    user: CurrentUser,
    db: DB,
    page: str | None = None,
    size: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    include_revoked: bool = True,
):
    """Filter by name, tag and upload date; newest first; paginated (BE A)."""
    page_number = parse_int(page, "page", 1, 1, 10**6)
    page_size = parse_int(size, "size", DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE)
    service = MaterialService(db)
    meeting = service.viewable(meeting_id, user)
    teacher_view, items = service.filtered(
        meeting,
        user,
        q,
        tag,
        parse_date(from_date, "from_date"),
        parse_date(to_date, "to_date"),
        include_revoked,
    )
    window, pagination = paginate(items, page_number, page_size)
    return ok({"items": [material_out(m, teacher_view) for m in window], "pagination": pagination})


@router.get("/meetings/{meeting_id}/documents/{document_id}")
def get_document(meeting_id: str, document_id: str, request: Request, user: CurrentUser, db: DB):
    service = MaterialService(db, request.app.state.storage)
    meeting, material = service.visible_document(meeting_id, document_id, user)
    return no_store(
        {
            **material_out(material, meeting.teacher_id == user.id),
            "download_url": service.download_url(material),
            "preview_url": service.preview_url(material),
            "expires_in": DOWNLOAD_URL_TTL_SECONDS,
        }
    )


@router.delete("/meetings/{meeting_id}/documents/{document_id}")
def delete_document(meeting_id: str, document_id: str, request: Request, user: CurrentUser, db: DB):
    MaterialService(db, request.app.state.storage).delete(meeting_id, document_id, user)
    return ok({"id": document_id, "deleted": True}, "Đã xoá tài liệu.")


@router.patch("/meetings/{meeting_id}/documents/{document_id}/share")
def share_document(meeting_id: str, document_id: str, data: ShareIn, user: CurrentUser, db: DB):
    """[] shares with the whole class; ids add those members only."""
    material = MaterialService(db).share(meeting_id, document_id, user, data.account_ids)
    return ok(material_out(material, teacher_view=True), "Đã chia sẻ tài liệu.")


@router.patch("/meetings/{meeting_id}/documents/{document_id}/unshare")
def unshare_document(meeting_id: str, document_id: str, data: ShareIn, user: CurrentUser, db: DB):
    """[] hides from everyone; ids remove only those members."""
    material = MaterialService(db).unshare(meeting_id, document_id, user, data.account_ids)
    return ok(material_out(material, teacher_view=True), "Đã bỏ chia sẻ tài liệu.")


@router.post("/meetings/{meeting_id}/documents/{document_id}/revoke")
def revoke_document(meeting_id: str, document_id: str, user: CurrentUser, db: DB):
    """Members and public links lose access; the file is kept for audit and restore."""
    material = MaterialService(db).revoke(meeting_id, document_id, user)
    return ok(
        {"id": material.id, "revoked": True, "revoked_at": material.revoked_at},
        "Đã thu hồi tài liệu.",
    )


@router.post("/meetings/{meeting_id}/documents/{document_id}/restore")
def restore_document(meeting_id: str, document_id: str, user: CurrentUser, db: DB):
    material = MaterialService(db).restore(meeting_id, document_id, user)
    return ok({"id": material.id, "revoked": False}, "Đã khôi phục tài liệu.")


@router.post("/meetings/{meeting_id}/documents/{document_id}/generate-share-link")
def generate_share_link(
    meeting_id: str,
    document_id: str,
    user: CurrentUser,
    db: DB,
    data: ShareLinkIn | None = None,
):
    """Public link without login (1-168 hours); calling again replaces the old token."""
    hours = data.expires_in_hours if data else 24
    material = MaterialService(db).generate_share_link(meeting_id, document_id, user, hours)
    return ok(
        {
            "share_path": share_path(material.share_token),
            "share_token": material.share_token,
            "expires_at": material.share_expires_at,
        },
        "Đã tạo link chia sẻ.",
    )


@share_router.get("/documents/{share_token}")
def shared_document(share_token: str, request: Request, db: DB):
    """No login: the token is the permission. 404 unknown, 410 revoked or expired."""
    service = MaterialService(db, request.app.state.storage)
    material = service.shared(share_token)
    return no_store(
        {
            **material_out(material, teacher_view=False),
            "download_url": service.download_url(material),
            "expires_in": DOWNLOAD_URL_TTL_SECONDS,
        }
    )
