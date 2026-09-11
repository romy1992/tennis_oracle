"""admin-editable scheduled job settings

Revision ID: 0037_scheduled_job_settings
Revises: 0036_runtime_secrets
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "0037_scheduled_job_settings"
down_revision: str | None = "0036_runtime_secrets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "scheduled_job_setting" in set(inspector.get_table_names()):
        return

    op.create_table(
        "scheduled_job_setting",
        sa.Column("job_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("schedule_kind", sa.String(length=32), nullable=False),
        sa.Column("clock_time", sa.String(length=5), nullable=True),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_status", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=150), nullable=True),
        sa.PrimaryKeyConstraint("job_key"),
    )
    op.create_index(
        "ix_scheduled_job_setting_updated_at",
        "scheduled_job_setting",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "scheduled_job_setting" in set(inspector.get_table_names()):
        op.drop_table("scheduled_job_setting")
