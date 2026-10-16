from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from app.core.document import Document


@dataclass(kw_only=True, eq=False)
class AnalysisJob(Document):
    __collection__: ClassVar[str] = "analysis_jobs"
    id: str | None = None
    recording_id: str | None = None
    # pending | processing | completed | failed
    state: str | None = None
    attempts: int | None = None
    lease_token: str | None = None
    lease_until: datetime | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(kw_only=True, eq=False)
class AnalysisResult(Document):
    __collection__: ClassVar[str] = "analysis_results"
    recording_id: str | None = None
    result: dict | None = None
    completed_at: datetime | None = None
