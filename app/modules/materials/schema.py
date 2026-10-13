from datetime import datetime

from pydantic import BaseModel

from app.core.schemas import ORMModel


class MaterialOut(ORMModel):
    id: str
    meeting_id: str
    uploaded_by: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    format: str | None = None
    tags: list[str] = []
    # Teacher view only (BE A sharing state); null for students.
    shared_with: list[str] | None = None
    shared_with_all: bool | None = None
    revoked: bool | None = None
    revoked_at: datetime | None = None
    share_path: str | None = None
    share_expires_at: datetime | None = None


class MaterialWithUrlOut(MaterialOut):
    download_url: str
    expires_in: int = 300


class ShareIn(BaseModel):
    account_ids: list[str] = []


class ShareLinkIn(BaseModel):
    # Validated in the service (integer 1-168, booleans rejected) to keep BE A's message.
    expires_in_hours: object = 24
