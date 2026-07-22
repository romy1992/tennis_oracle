"""prematch_odds_snapshot append-only odds history

Revision ID: 0014_prematch_odds_snapshot
Revises: 0013_published_prediction
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0014_prematch_odds_snapshot"
down_revision: Union[str, None] = "0013_published_prediction"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "prematch_odds_snapshot" in tables:
        return

    op.create_table(
        "prematch_odds_snapshot",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_key", sa.Integer(), nullable=False),
        sa.Column("selection", sa.String(), nullable=False),
        sa.Column("bookmaker", sa.String(), nullable=False),
        sa.Column("odds", sa.Float(), nullable=False),
        sa.Column("implied_probability", sa.Float(), nullable=False),
        sa.Column("margin", sa.Float(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("snapshot_type", sa.String(), nullable=False),
        sa.Column("detection_hash", sa.String(length=64), nullable=False),
        sa.Column("market_side", sa.String(), nullable=True),
        sa.Column("player_1_name", sa.String(), nullable=True),
        sa.Column("player_2_name", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "detection_hash",
            name="uq_prematch_odds_snapshot_detection_hash",
        ),
    )
    op.create_index(
        "ix_prematch_odds_snapshot_event_key",
        "prematch_odds_snapshot",
        ["event_key"],
        unique=False,
    )
    op.create_index(
        "ix_prematch_odds_snapshot_captured_at",
        "prematch_odds_snapshot",
        ["captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_prematch_odds_snapshot_snapshot_type",
        "prematch_odds_snapshot",
        ["snapshot_type"],
        unique=False,
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "prematch_odds_snapshot" not in tables:
        return

    op.drop_index(
        "ix_prematch_odds_snapshot_snapshot_type",
        table_name="prematch_odds_snapshot",
    )
    op.drop_index(
        "ix_prematch_odds_snapshot_captured_at",
        table_name="prematch_odds_snapshot",
    )
    op.drop_index(
        "ix_prematch_odds_snapshot_event_key",
        table_name="prematch_odds_snapshot",
    )
    op.drop_table("prematch_odds_snapshot")
