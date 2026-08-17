"""widen walk-forward version columns for multi-market labels

``walk_forward_fold.model_version`` was ``String(8)`` (fits ``v1``-``v4``) and
``walk_forward_run.versions_requested`` was ``String(64)``. Extra-market walk
forward now uses longer labels (``first_set_winner_v2``, ``over_under_games_v1``,
20 chars each) that would overflow the old column length on Postgres.

Revision ID: 0031_widen_wf_versions
Revises: 0030_multi_market_columns
Create Date: 2026-08-17

Note: keep the revision id <=32 chars — it's written into
``alembic_version.version_num``, which alembic creates as ``VARCHAR(32)`` by
default; a longer id fails with StringDataRightTruncation on Postgres.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0031_widen_wf_versions"
down_revision: Union[str, None] = "0030_multi_market_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "walk_forward_fold" in tables:
        with op.batch_alter_table("walk_forward_fold") as batch_op:
            batch_op.alter_column(
                "model_version",
                existing_type=sa.String(length=8),
                type_=sa.String(length=32),
                existing_nullable=False,
            )

    if "walk_forward_run" in tables:
        with op.batch_alter_table("walk_forward_run") as batch_op:
            batch_op.alter_column(
                "versions_requested",
                existing_type=sa.String(length=64),
                type_=sa.String(length=128),
                existing_nullable=False,
            )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "walk_forward_run" in tables:
        with op.batch_alter_table("walk_forward_run") as batch_op:
            batch_op.alter_column(
                "versions_requested",
                existing_type=sa.String(length=128),
                type_=sa.String(length=64),
                existing_nullable=False,
            )

    if "walk_forward_fold" in tables:
        with op.batch_alter_table("walk_forward_fold") as batch_op:
            batch_op.alter_column(
                "model_version",
                existing_type=sa.String(length=32),
                type_=sa.String(length=8),
                existing_nullable=False,
            )
