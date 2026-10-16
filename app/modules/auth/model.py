from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from app.core.document import Document


@dataclass(kw_only=True, eq=False)
class User(Document):
    __collection__: ClassVar[str] = "users"
    id: str | None = None
    email: str | None = None
    password_hash: str | None = None
    full_name: str | None = None
    # teacher | student | admin
    role: str | None = None
    created_at: datetime | None = None


@dataclass(kw_only=True, eq=False)
class RefreshSession(Document):
    __collection__: ClassVar[str] = "refresh_sessions"
    jti: str | None = None
    user_id: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
