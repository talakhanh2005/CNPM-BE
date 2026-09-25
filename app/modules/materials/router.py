import asyncio

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import DB, CurrentUser, Teacher
from app.core.errors import AppError
from app.core.schemas import Envelope, ok
from app.modules.materials.schema import MaterialOut
from app.modules.materials.service import MIMES, MaterialService
from app.modules.meetings.service import MeetingService
from app.modules.recordings.schema import PlaybackOut

router = APIRouter(tags=["Teaching materials"])


@router.post(
    "/meetings/{meeting_id}/materials",
    status_code=201,
    response_model=Envelope[MaterialOut],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                mime: {"schema": {"type": "string", "format": "binary"}} for mime in MIMES.values()
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
        return ok(material, "Material uploaded")


@router.get("/meetings/{meeting_id}/materials", response_model=Envelope[list[MaterialOut]])
def list_materials(
    meeting_id: str,
    user: CurrentUser,
    db: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    return ok(MaterialService(db).list(meeting_id, user, offset, limit))


@router.get("/materials/{material_id}/download", response_model=Envelope[PlaybackOut])
def download(material_id: str, request: Request, user: CurrentUser, db: DB):
    material = MaterialService(db).require(material_id, user)
    return ok(
        {
            "url": request.app.state.storage.document_download_url(material.public_id),
            "expires_in": 300,
        }
    )
