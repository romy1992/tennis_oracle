"""public model registry entries

Revision ID: 0024_public_model_registry
Revises: 0023_background_job_progress
Create Date: 2026-07-29

Official lifecycle registry for the public/live model (ML-07).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0024_public_model_registry"
down_revision: Union[str, None] = "0023_background_job_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "public_model_registry_entry" not in tables:
        op.create_table(
            "public_model_registry_entry",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("model_version", sa.String(length=8), nullable=False),
            sa.Column("model_name", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="candidate"),
            sa.Column("activated_at", sa.DateTime(), nullable=True),
            sa.Column("retired_at", sa.DateTime(), nullable=True),
            sa.Column(
                "approval_metrics_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("motivation", sa.Text(), nullable=True),
            sa.Column(
                "artifacts_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("supersedes_entry_id", sa.Integer(), nullable=True),
            sa.Column("walk_forward_run_id", sa.Integer(), nullable=True),
            sa.Column("calibration_run_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=False, server_default="api"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["supersedes_entry_id"],
                ["public_model_registry_entry.id"],
            ),
            sa.ForeignKeyConstraint(
                ["walk_forward_run_id"],
                ["walk_forward_run.id"],
            ),
            sa.ForeignKeyConstraint(
                ["calibration_run_id"],
                ["calibration_run.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_public_model_registry_entry_model_version",
            "public_model_registry_entry",
            ["model_version"],
        )
        op.create_index(
            "ix_public_model_registry_entry_model_name",
            "public_model_registry_entry",
            ["model_name"],
        )
        op.create_index(
            "ix_public_model_registry_entry_status",
            "public_model_registry_entry",
            ["status"],
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "public_model_registry_entry" in tables:
        op.drop_table("public_model_registry_entry")
