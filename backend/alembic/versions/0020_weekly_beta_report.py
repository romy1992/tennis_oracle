"""weekly beta report snapshots

Revision ID: 0020_weekly_beta_report
Revises: 0019_telegram_feedback
Create Date: 2026-07-27

Adds weekly_beta_report for persisted Monday–Sunday beta KPIs and admin
Telegram summary delivery status.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0020_weekly_beta_report"
down_revision: Union[str, None] = "0019_telegram_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "weekly_beta_report" in tables:
        return

    op.create_table(
        "weekly_beta_report",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("week_label", sa.String(length=16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("telegram_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("telegram_error", sa.Text(), nullable=True),
        sa.Column("telegram_sent_at", sa.DateTime(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("generated_by", sa.String(length=64), nullable=False, server_default="job"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("week_start", "week_end", name="uq_weekly_beta_report_week"),
    )
    op.create_index("ix_weekly_beta_report_week_start", "weekly_beta_report", ["week_start"])
    op.create_index("ix_weekly_beta_report_week_end", "weekly_beta_report", ["week_end"])
    op.create_index("ix_weekly_beta_report_week_label", "weekly_beta_report", ["week_label"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "weekly_beta_report" not in tables:
        return
    op.drop_index("ix_weekly_beta_report_week_label", table_name="weekly_beta_report")
    op.drop_index("ix_weekly_beta_report_week_end", table_name="weekly_beta_report")
    op.drop_index("ix_weekly_beta_report_week_start", table_name="weekly_beta_report")
    op.drop_table("weekly_beta_report")
