from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from app.core.document import Document


@dataclass(kw_only=True, eq=False)
class Material(Document):
    """Teaching material (BE B) and shared document (BE A) in one collection."""

    __collection__: ClassVar[str] = "materials"
    id: str | None = None
    meeting_id: str | None = None
    uploaded_by: str | None = None
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    public_id: str | None = None
    created_at: datetime | None = None
    # Sharing fields merged from BE A documents.
    format: str | None = None
    resource_type: str | None = None
    tags: list | None = None
    shared_with: list | None = None
    shared_with_all: bool | None = None
    revoked_at: datetime | None = None
    share_token: str | None = None
    share_expires_at: datetime | None = None
