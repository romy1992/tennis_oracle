"""next fixtures and match predictions

Revision ID: 0003_next_fixtures
Revises: 0002_ml_ready_schema
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "0003_next_fixtures"
down_revision: Union[str, None] = "0002_ml_ready_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "next_fixture" not in tables:
        op.create_table(
            "next_fixture",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("event_key", sa.Integer(), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=True),
            sa.Column("event_time", sa.Time(), nullable=True),
            sa.Column("event_first_player", sa.String(), nullable=True),
            sa.Column("first_player_key", sa.Integer(), nullable=True),
            sa.Column("event_second_player", sa.String(), nullable=True),
            sa.Column("second_player_key", sa.Integer(), nullable=True),
            sa.Column("tournament_name", sa.String(), nullable=True),
            sa.Column("tournament_key", sa.Integer(), nullable=True),
            sa.Column("tournament_round", sa.String(), nullable=True),
            sa.Column("surface", sa.String(), nullable=True),
            sa.Column("event_status", sa.String(), nullable=True),
            sa.Column("event_type_type", sa.String(), nullable=True),
            sa.Column("odds", sa.JSON(), nullable=True),
            sa.Column("imported_at", sa.DateTime(), nullable=True),
            sa.Column("week_start", sa.Date(), nullable=True),
            sa.Column("week_end", sa.Date(), nullable=True),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("is_completed", sa.Boolean(), nullable=True),
            sa.Column("moved_to_fixture_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_key"),
        )

    next_fixture_indexes = {
        index["name"] for index in inspector.get_indexes("next_fixture")
    }
    if "ix_next_fixture_event_date" not in next_fixture_indexes:
        op.create_index(
            op.f("ix_next_fixture_event_date"),
            "next_fixture",
            ["event_date"],
            unique=False,
        )

    if "match_prediction" not in tables:
        op.create_table(
            "match_prediction",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("event_key", sa.Integer(), nullable=False),
            sa.Column("model_version", sa.String(), nullable=False),
            sa.Column("predicted_at", sa.DateTime(), nullable=False),
            sa.Column("prob_player_1_win", sa.Float(), nullable=True),
            sa.Column("predicted_winner", sa.String(), nullable=True),
            sa.Column("actual_winner", sa.String(), nullable=True),
            sa.Column("is_correct", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "event_key",
                "model_version",
                name="uq_match_prediction_event_version",
            ),
        )

    match_prediction_indexes = {
        index["name"] for index in inspector.get_indexes("match_prediction")
    }
    if "ix_match_prediction_event_key" not in match_prediction_indexes:
        op.create_index(
            op.f("ix_match_prediction_event_key"),
            "match_prediction",
            ["event_key"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_match_prediction_event_key"), table_name="match_prediction")
    op.drop_table("match_prediction")
    op.drop_index(op.f("ix_next_fixture_event_date"), table_name="next_fixture")
    op.drop_table("next_fixture")
