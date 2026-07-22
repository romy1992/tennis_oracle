"""published_prediction immutable publication ledger

Revision ID: 0013_published_prediction
Revises: 0012_rate_limit_bucket
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0013_published_prediction"
down_revision: Union[str, None] = "0012_rate_limit_bucket"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "published_prediction" in tables:
        return

    op.create_table(
        "published_prediction",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("publication_id", sa.String(length=36), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("previous_version_id", sa.Integer(), nullable=True),
        sa.Column("event_key", sa.Integer(), nullable=False),
        sa.Column("selection", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("odds", sa.Float(), nullable=True),
        sa.Column("void_odds", sa.Float(), nullable=True),
        sa.Column("edge", sa.Float(), nullable=True),
        sa.Column("unit_stake", sa.Float(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("publication_source", sa.String(), nullable=False),
        sa.Column("initial_status", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("player_1_name", sa.String(), nullable=True),
        sa.Column("player_2_name", sa.String(), nullable=True),
        sa.Column("tournament_name", sa.String(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("event_time", sa.Time(), nullable=True),
        sa.Column("match_prediction_id", sa.Integer(), nullable=True),
        sa.Column("betting_slip_pick_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["previous_version_id"],
            ["published_prediction.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publication_id",
            "content_version",
            name="uq_published_prediction_publication_version",
        ),
    )
    op.create_index(
        "ix_published_prediction_publication_id",
        "published_prediction",
        ["publication_id"],
        unique=False,
    )
    op.create_index(
        "ix_published_prediction_previous_version_id",
        "published_prediction",
        ["previous_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_published_prediction_event_key",
        "published_prediction",
        ["event_key"],
        unique=False,
    )
    op.create_index(
        "ix_published_prediction_published_at",
        "published_prediction",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        "ix_published_prediction_match_prediction_id",
        "published_prediction",
        ["match_prediction_id"],
        unique=False,
    )
    op.create_index(
        "ix_published_prediction_betting_slip_pick_id",
        "published_prediction",
        ["betting_slip_pick_id"],
        unique=False,
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "published_prediction" not in tables:
        return

    op.drop_index(
        "ix_published_prediction_betting_slip_pick_id",
        table_name="published_prediction",
    )
    op.drop_index(
        "ix_published_prediction_match_prediction_id",
        table_name="published_prediction",
    )
    op.drop_index(
        "ix_published_prediction_published_at",
        table_name="published_prediction",
    )
    op.drop_index(
        "ix_published_prediction_event_key",
        table_name="published_prediction",
    )
    op.drop_index(
        "ix_published_prediction_previous_version_id",
        table_name="published_prediction",
    )
    op.drop_index(
        "ix_published_prediction_publication_id",
        table_name="published_prediction",
    )
    op.drop_table("published_prediction")
