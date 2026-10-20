from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.core.db import new_id, now


@dataclass(kw_only=True)
class AnalysisJob:
    __collection__: ClassVar[str] = "analysis_jobs"
    id: str = field(default_factory=new_id)
    recording_id: str
    state: str = "pending"
    attempts: int = 0
    lease_token: str | None = None
    lease_until: datetime | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)


@dataclass(kw_only=True)
class AnalysisResult:
    __collection__: ClassVar[str] = "analysis_results"
    recording_id: str
    result: dict
    completed_at: datetime = field(default_factory=now)
