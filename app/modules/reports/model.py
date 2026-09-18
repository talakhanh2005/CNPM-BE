from dataclasses import dataclass


@dataclass(frozen=True)
class ReportSelection:
    """Read-model selector; BE-07 projects analysis_results and emotion_samples."""

    source: str = "auto"
    offset: int = 0
    limit: int = 500
