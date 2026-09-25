from datetime import datetime

from app.core.schemas import ORMModel


class MaterialOut(ORMModel):
    id: str
    meeting_id: str
    uploaded_by: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
