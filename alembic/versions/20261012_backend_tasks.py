"""Admin RBAC. Participant memberships are authoritative for 1-N rooms."""

from alembic import op

revision = "20261012_backend"
down_revision = "20260925_classroom"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite table rebuild must happen with FK checks disabled before BEGIN.
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_user_role", type_="check")
        batch.create_check_constraint("ck_user_role", "role IN ('admin', 'teacher', 'student')")

    op.create_index(
        "ix_emotion_frame_lookup", "emotion_samples", ["meeting_id", "student_id", "frame_id"]
    )


def downgrade():
    op.drop_index("ix_emotion_frame_lookup", table_name="emotion_samples")
    # Refuse to silently discard or demote existing administrators.
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_user_role", type_="check")
        batch.create_check_constraint("ck_user_role", "role IN ('teacher', 'student')")
