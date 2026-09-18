"""SQL Server Unicode fields; original initial migration remains immutable."""

import sqlalchemy as sa

from alembic import op

revision = "20260915_unicode"
down_revision = "43b6b199dfcd"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().dialect.name == "mssql":
        op.alter_column(
            "users",
            "full_name",
            existing_type=sa.String(150),
            type_=sa.Unicode(150),
            existing_nullable=False,
        )
        op.alter_column(
            "analysis_jobs",
            "error_message",
            existing_type=sa.String(256),
            type_=sa.Unicode(256),
            existing_nullable=True,
        )


def downgrade():
    if op.get_context().dialect.name == "mssql":
        op.alter_column(
            "analysis_jobs",
            "error_message",
            existing_type=sa.Unicode(256),
            type_=sa.String(256),
            existing_nullable=True,
        )
        op.alter_column(
            "users",
            "full_name",
            existing_type=sa.Unicode(150),
            type_=sa.String(150),
            existing_nullable=False,
        )
