"""add scheduled report job ledger

Revision ID: 0035_scheduled_report_jobs
Revises: 0034_widen_calibration_versions
Create Date: 2026-08-30

The table is additive. It coordinates daily/weekly scheduler claims across
multiple workers and records the runtime source of every claimed schedule.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0035_scheduled_report_jobs"
down_revision: Union[str, None] = "0034_widen_calibration_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "scheduled_report_job" in set(inspector.get_table_names()):
        return

    op.create_table(
        "scheduled_report_job",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("schedule_key", sa.String(length=96), nullable=False),
        sa.Column("job_name", sa.String(length=48), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_environment", sa.String(length=32), nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("source_hostname", sa.String(length=255), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("global_update_run_id", sa.Integer(), nullable=True),
        sa.Column("walk_forward_run_id", sa.Integer(), nullable=True),
        sa.Column("calibration_run_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("report_json", sa.Text(), nullable=True),
        sa.Column("email_status", sa.String(length=32), nullable=True),
        sa.Column("email_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["calibration_run_id"],
            ["calibration_run.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["global_update_run_id"],
            ["global_update_run.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["walk_forward_run_id"],
            ["walk_forward_run.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_key", name="uq_scheduled_report_job_schedule_key"),
    )
    op.create_index(
        "ix_scheduled_report_job_schedule_key",
        "scheduled_report_job",
        ["schedule_key"],
        unique=True,
    )
    op.create_index(
        "ix_scheduled_report_job_job_name",
        "scheduled_report_job",
        ["job_name"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_report_job_scheduled_for",
        "scheduled_report_job",
        ["scheduled_for"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_report_job_status",
        "scheduled_report_job",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_report_job_global_update_run_id",
        "scheduled_report_job",
        ["global_update_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_report_job_walk_forward_run_id",
        "scheduled_report_job",
        ["walk_forward_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_scheduled_report_job_calibration_run_id",
        "scheduled_report_job",
        ["calibration_run_id"],
        unique=False,
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "scheduled_report_job" in set(inspector.get_table_names()):
        op.drop_table("scheduled_report_job")
