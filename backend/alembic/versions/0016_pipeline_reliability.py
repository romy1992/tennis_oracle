"""pipeline lock + global update reliability fields

Revision ID: 0016_pipeline_reliability
Revises: 0015_pp_live_idempotency
Create Date: 2026-07-25

Adds distributed pipeline_lock table and columns on global_update_run for
cancel-across-workers, phase persistence, and crash/resume recovery.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0016_pipeline_reliability"
down_revision: Union[str, None] = "0015_pp_live_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "pipeline_lock" not in tables:
        op.create_table(
            "pipeline_lock",
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("owner_token", sa.String(length=64), nullable=True),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("acquired_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("name"),
        )
        op.execute(
            sa.text(
                "INSERT INTO pipeline_lock (name, owner_token, run_id, "
                "acquired_at, expires_at, heartbeat_at) "
                "VALUES ('global_update', NULL, NULL, NULL, NULL, NULL)"
            )
        )

    if "global_update_run" in tables:
        columns = {col["name"] for col in inspector.get_columns("global_update_run")}
        if "cancel_requested" not in columns:
            op.add_column(
                "global_update_run",
                sa.Column(
                    "cancel_requested",
                    sa.String(),
                    nullable=False,
                    server_default="false",
                ),
            )
        if "phases_json" not in columns:
            op.add_column(
                "global_update_run",
                sa.Column("phases_json", sa.Text(), nullable=True),
            )
        if "worker_id" not in columns:
            op.add_column(
                "global_update_run",
                sa.Column("worker_id", sa.String(length=64), nullable=True),
            )
        if "resume_count" not in columns:
            op.add_column(
                "global_update_run",
                sa.Column(
                    "resume_count",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                ),
            )
        if "sync_cloud" not in columns:
            op.add_column(
                "global_update_run",
                sa.Column(
                    "sync_cloud",
                    sa.String(),
                    nullable=False,
                    server_default="false",
                ),
            )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "global_update_run" in tables:
        columns = {col["name"] for col in inspector.get_columns("global_update_run")}
        for col in (
            "sync_cloud",
            "resume_count",
            "worker_id",
            "phases_json",
            "cancel_requested",
        ):
            if col in columns:
                op.drop_column("global_update_run", col)

    if "pipeline_lock" in tables:
        op.drop_table("pipeline_lock")
