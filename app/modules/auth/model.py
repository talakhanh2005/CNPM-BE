from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.core.db import new_id, now


@dataclass(kw_only=True)
class User:
    __collection__: ClassVar[str] = "users"
    id: str = field(default_factory=new_id)
    email: str
    password_hash: str
    full_name: str
    role: str
    created_at: datetime = field(default_factory=now)


@dataclass(kw_only=True)
class RefreshSession:
    __collection__: ClassVar[str] = "refresh_sessions"
    jti: str
    user_id: str
    expires_at: datetime
    revoked_at: datetime | None = None
