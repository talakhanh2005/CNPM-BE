"""Import all tables for Alembic; importing app does not create or mutate a database."""

from app.modules.analysis.model import AnalysisJob, AnalysisResult
from app.modules.auth.model import RefreshSession, User
from app.modules.emotion_labels.model import EmotionLabel
from app.modules.emotions.model import EmotionSample
from app.modules.materials.model import Material
from app.modules.meetings.model import Meeting, Participant
from app.modules.recordings.model import Recording
from app.modules.timeline.model import EmotionSegment

__all__ = [
    "User",
    "RefreshSession",
    "Meeting",
    "Participant",
    "Recording",
    "AnalysisJob",
    "AnalysisResult",
    "EmotionSample",
    "Material",
    "EmotionLabel",
    "EmotionSegment",
]
