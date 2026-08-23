"""widen calibration version columns for multi-market labels

Revision ID: 0034_widen_calibration_versions
Revises: 0033_slip_strategy_metadata
Create Date: 2026-08-22

The extra-market identifiers ``first_set_winner_v2`` and
``over_under_games_v1`` do not fit the original match-winner-only VARCHAR(8)
column. This migration is additive and does not rewrite or delete run data.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0034_widen_calibration_versions"
down_revision: Union[str, None] = "0033_slip_strategy_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "calibration_result" in tables:
        with op.batch_alter_table("calibration_result") as batch_op:
            batch_op.alter_column(
                "model_version",
                existing_type=sa.String(length=8),
                type_=sa.String(length=32),
                existing_nullable=False,
            )

    if "calibration_run" in tables:
        with op.batch_alter_table("calibration_run") as batch_op:
            batch_op.alter_column(
                "versions_requested",
                existing_type=sa.String(length=64),
                type_=sa.String(length=128),
                existing_nullable=False,
            )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "calibration_run" in tables:
        with op.batch_alter_table("calibration_run") as batch_op:
            batch_op.alter_column(
                "versions_requested",
                existing_type=sa.String(length=128),
                type_=sa.String(length=64),
                existing_nullable=False,
            )

    if "calibration_result" in tables:
        with op.batch_alter_table("calibration_result") as batch_op:
            batch_op.alter_column(
                "model_version",
                existing_type=sa.String(length=32),
                type_=sa.String(length=8),
                existing_nullable=False,
            )
