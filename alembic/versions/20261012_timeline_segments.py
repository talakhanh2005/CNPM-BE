"""Contract v1 (BE-TU-03): emotion_segments table and realtime model_version."""

import sqlalchemy as sa

from alembic import op

revision = "20261012_timeline"
down_revision = "20261012_merge_a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("emotion_samples", sa.Column("model_version", sa.String(64), nullable=True))
    op.create_table(
        "emotion_segments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "analysis_job_id", sa.String(36), sa.ForeignKey("analysis_jobs.id"), nullable=True
        ),
        sa.Column("recording_id", sa.String(36), sa.ForeignKey("recordings.id"), nullable=False),
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id"), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("emotion", sa.String(16), nullable=False),
        sa.Column("avg_confidence", sa.Float(), nullable=True),
        sa.Column("student_id", sa.String(36), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_segments_recording_start", "emotion_segments", ["recording_id", "start_seconds"]
    )
    op.create_index("ix_emotion_segments_meeting_id", "emotion_segments", ["meeting_id"])


def downgrade():
    op.drop_index("ix_emotion_segments_meeting_id", table_name="emotion_segments")
    op.drop_index("ix_segments_recording_start", table_name="emotion_segments")
    op.drop_table("emotion_segments")
    with op.batch_alter_table("emotion_samples") as batch:
        batch.drop_column("model_version")
