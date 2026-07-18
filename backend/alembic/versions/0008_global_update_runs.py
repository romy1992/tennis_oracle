"""global update runs and items

Revision ID: 0008_global_update_runs
Revises: 0007_betting_slip_value_fields
Create Date: 2026-07-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0008_global_update_runs"
down_revision: Union[str, None] = "0007_betting_slip_value_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "global_update_run" not in tables:
        op.create_table(
            "global_update_run",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("run_date", sa.Date(), nullable=False),
            sa.Column("origin", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("current_phase", sa.String(), nullable=True),
            sa.Column("progress_pct", sa.Float(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("force", sa.String(), nullable=False),
            sa.Column("versions_processed", sa.Integer(), nullable=False),
            sa.Column("models_processed", sa.Integer(), nullable=False),
            sa.Column("combinations_completed", sa.Integer(), nullable=False),
            sa.Column("combinations_failed", sa.Integer(), nullable=False),
            sa.Column("combinations_skipped", sa.Integer(), nullable=False),
            sa.Column("fixtures_processed", sa.Integer(), nullable=False),
            sa.Column("slips_generated", sa.Integer(), nullable=False),
            sa.Column("report_json", sa.Text(), nullable=True),
            sa.Column("errors_json", sa.Text(), nullable=True),
            sa.Column("warnings_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = inspect(op.get_bind())
    run_indexes = {index["name"] for index in inspector.get_indexes("global_update_run")}
    if "ix_global_update_run_run_date" not in run_indexes:
        op.create_index(
            op.f("ix_global_update_run_run_date"),
            "global_update_run",
            ["run_date"],
            unique=False,
        )
    if "ix_global_update_run_status" not in run_indexes:
        op.create_index(
            op.f("ix_global_update_run_status"),
            "global_update_run",
            ["status"],
            unique=False,
        )

    if "global_update_run_item" not in tables:
        op.create_table(
            "global_update_run_item",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("model_version", sa.String(), nullable=False),
            sa.Column("model_name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("predictions_generated", sa.Integer(), nullable=False),
            sa.Column("slips_generated", sa.Integer(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("warnings_json", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["run_id"], ["global_update_run.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "run_id",
                "model_version",
                "model_name",
                name="uq_global_update_run_item",
            ),
        )

    inspector = inspect(op.get_bind())
    item_indexes = {index["name"] for index in inspector.get_indexes("global_update_run_item")}
    if "ix_global_update_run_item_run_id" not in item_indexes:
        op.create_index(
            op.f("ix_global_update_run_item_run_id"),
            "global_update_run_item",
            ["run_id"],
            unique=False,
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "global_update_run_item" in tables:
        op.drop_table("global_update_run_item")
    if "global_update_run" in tables:
        op.drop_table("global_update_run")
