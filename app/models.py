"""Import all tables for Alembic; importing app does not create or mutate a database."""

from app.modules.analysis.model import AnalysisJob, AnalysisResult
from app.modules.auth.model import RefreshSession, User
from app.modules.emotions.model import EmotionSample
from app.modules.meetings.model import Meeting, Participant
from app.modules.recordings.model import Recording

__all__ = [
    "User",
    "RefreshSession",
    "Meeting",
    "Participant",
    "Recording",
    "AnalysisJob",
    "AnalysisResult",
    "EmotionSample",
]
