"""Associate recordings with students without guessing ownership for old videos."""

import sqlalchemy as sa

from alembic import op

revision = "20261012_recording_student"
down_revision = "20261012_backend"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("recordings") as batch:
        batch.add_column(sa.Column("student_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_recordings_student", "users", ["student_id"], ["id"])
        batch.create_index("ix_recordings_student_id", ["student_id"])


def downgrade():
    with op.batch_alter_table("recordings") as batch:
        batch.drop_index("ix_recordings_student_id")
        batch.drop_constraint("fk_recordings_student", type_="foreignkey")
        batch.drop_column("student_id")
