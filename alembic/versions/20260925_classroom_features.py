"""One-to-one meetings, realtime frame metadata and teaching materials."""

import sqlalchemy as sa

from alembic import op

revision = "20260925_classroom"
down_revision = "20260915_unicode"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "meetings", sa.Column("mode", sa.String(16), nullable=False, server_default="realtime")
    )
    if op.get_context().dialect.name == "sqlite":
        # SQLite can add a nullable FK column directly, preserving referenced legacy rows.
        op.execute("ALTER TABLE meetings ADD COLUMN student_id VARCHAR(36) REFERENCES users(id)")
    else:
        op.add_column("meetings", sa.Column("student_id", sa.String(36), nullable=True))
        op.create_foreign_key("fk_meeting_student", "meetings", "users", ["student_id"], ["id"])
    # A legacy room with several students retains its history but cannot accept another student.
    op.add_column("emotion_samples", sa.Column("frame_id", sa.String(64), nullable=True))
    op.add_column(
        "emotion_samples", sa.Column("received_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("emotion_samples", sa.Column("probabilities", sa.JSON(), nullable=True))
    op.add_column("emotion_samples", sa.Column("face_id", sa.String(128), nullable=True))
    op.add_column(
        "emotion_samples",
        sa.Column("face_detected", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("emotion_samples", sa.Column("failure_reason", sa.String(16), nullable=True))
    op.add_column(
        "emotion_samples",
        sa.Column("logged", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "materials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("meeting_id", sa.String(36), sa.ForeignKey("meetings.id"), nullable=False),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.Unicode(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(256), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_materials_meeting_id", "materials", ["meeting_id"])
    op.create_index(
        "ix_emotion_received", "emotion_samples", ["meeting_id", "student_id", "received_at"]
    )
    op.create_index(
        "ix_emotion_logged",
        "emotion_samples",
        ["meeting_id", "student_id", "logged", "received_at"],
    )


def downgrade():
    op.drop_table("materials")
    op.drop_index("ix_emotion_logged", table_name="emotion_samples")
    op.drop_index("ix_emotion_received", table_name="emotion_samples")
    for column in (
        "logged",
        "failure_reason",
        "face_detected",
        "face_id",
        "probabilities",
        "received_at",
        "frame_id",
    ):
        op.drop_column("emotion_samples", column)
    if op.get_context().dialect.name != "sqlite":
        op.drop_constraint("fk_meeting_student", "meetings", type_="foreignkey")
    op.drop_column("meetings", "student_id")
    op.drop_column("meetings", "mode")
