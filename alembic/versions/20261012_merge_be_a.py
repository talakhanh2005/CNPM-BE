"""Merge BE A features: room metadata, multi-student rooms, shared documents, admin, v1 emotions."""

import sqlalchemy as sa

from alembic import op

revision = "20261012_merge_a"
down_revision = "20260925_classroom"
branch_labels = None
depends_on = None


def _replace_check(table, name, condition):
    # SQLite cannot alter CHECK constraints in place; batch mode recreates the table there.
    with op.batch_alter_table(table, recreate="auto") as batch:
        batch.drop_constraint(name, type_="check")
        batch.create_check_constraint(name, condition)


def upgrade():
    _replace_check("users", "ck_user_role", "role IN ('teacher', 'student', 'admin')")
    _replace_check(
        "participants", "ck_participant_status", "status IN ('joined','left','disconnected')"
    )
    op.add_column(
        "participants", sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.add_column("meetings", sa.Column("name", sa.Unicode(100), nullable=True))
    op.add_column("meetings", sa.Column("description", sa.Unicode(500), nullable=True))
    op.add_column("meetings", sa.Column("tags", sa.JSON(), nullable=True))
    op.add_column(
        "meetings",
        sa.Column("participant_mode", sa.String(16), nullable=True, server_default="free"),
    )
    op.add_column(
        "meetings", sa.Column("duration_minutes", sa.Integer(), nullable=True, server_default="45")
    )
    op.add_column("meetings", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "meetings",
        sa.Column("recording_status", sa.String(16), nullable=True, server_default="none"),
    )
    op.add_column("meetings", sa.Column("recording_url", sa.String(2048), nullable=True))
    op.add_column("meetings", sa.Column("recording_public_id", sa.String(256), nullable=True))
    op.add_column("meetings", sa.Column("recording_resource_type", sa.String(16), nullable=True))
    op.add_column(
        "meetings", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("meetings", sa.Column("failed_reason", sa.String(64), nullable=True))
    op.create_index("ix_meetings_recording_public_id", "meetings", ["recording_public_id"])

    op.add_column("materials", sa.Column("format", sa.String(16), nullable=True))
    op.add_column(
        "materials", sa.Column("resource_type", sa.String(16), nullable=True, server_default="raw")
    )
    op.add_column("materials", sa.Column("tags", sa.JSON(), nullable=True))
    op.add_column("materials", sa.Column("shared_with", sa.JSON(), nullable=True))
    # Existing BE B materials were visible to every member: keep that for old rows.
    op.add_column(
        "materials",
        sa.Column("shared_with_all", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("materials", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("materials", sa.Column("share_token", sa.String(64), nullable=True))
    op.add_column(
        "materials", sa.Column("share_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_materials_share_token", "materials", ["share_token"])

    op.create_table(
        "emotion_labels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Unicode(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("media_url", sa.String(2048), nullable=True),
        sa.Column("media_public_id", sa.String(256), nullable=True),
        sa.Column("media_resource_type", sa.String(16), nullable=True),
    )
    op.create_index("ix_emotion_labels_user_id", "emotion_labels", ["user_id"])


def downgrade():
    op.drop_index("ix_emotion_labels_user_id", table_name="emotion_labels")
    op.drop_table("emotion_labels")
    op.drop_index("ix_materials_share_token", table_name="materials")
    for column in (
        "share_expires_at",
        "share_token",
        "revoked_at",
        "shared_with_all",
        "shared_with",
        "tags",
        "resource_type",
        "format",
    ):
        with op.batch_alter_table("materials") as batch:
            batch.drop_column(column)
    op.drop_index("ix_meetings_recording_public_id", table_name="meetings")
    for column in (
        "failed_reason",
        "processing_started_at",
        "recording_resource_type",
        "recording_public_id",
        "recording_url",
        "recording_status",
        "deleted_at",
        "duration_minutes",
        "participant_mode",
        "tags",
        "description",
        "name",
    ):
        with op.batch_alter_table("meetings") as batch:
            batch.drop_column(column)
    with op.batch_alter_table("participants") as batch:
        batch.drop_column("disconnected_at")
    _replace_check("participants", "ck_participant_status", "status IN ('joined','left')")
    _replace_check("users", "ck_user_role", "role IN ('teacher', 'student')")
