"""betting slips persistence

Revision ID: 0005_betting_slips
Revises: 0004_prediction_model_name
Create Date: 2026-06-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "0005_betting_slips"
down_revision: Union[str, None] = "0004_prediction_model_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "betting_slip" not in tables:
        op.create_table(
            "betting_slip",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("slip_date", sa.Date(), nullable=False),
            sa.Column("slip_key", sa.String(), nullable=False),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("model_version", sa.String(), nullable=False),
            sa.Column("model_name", sa.String(), nullable=False),
            sa.Column("pick_count", sa.Integer(), nullable=False),
            sa.Column("combined_odds", sa.Float(), nullable=False),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "slip_date",
                "slip_key",
                "model_version",
                "model_name",
                name="uq_betting_slip_date_key_model",
            ),
        )

    inspector = inspect(op.get_bind())
    betting_slip_indexes = {
        index["name"] for index in inspector.get_indexes("betting_slip")
    }
    if "ix_betting_slip_slip_date" not in betting_slip_indexes:
        op.create_index(
            op.f("ix_betting_slip_slip_date"),
            "betting_slip",
            ["slip_date"],
            unique=False,
        )

    if "betting_slip_pick" not in tables:
        op.create_table(
            "betting_slip_pick",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("betting_slip_id", sa.Integer(), nullable=False),
            sa.Column("event_key", sa.Integer(), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=True),
            sa.Column("event_time", sa.Time(), nullable=True),
            sa.Column("tournament_name", sa.String(), nullable=True),
            sa.Column("surface", sa.String(), nullable=True),
            sa.Column("player_1_name", sa.String(), nullable=True),
            sa.Column("player_2_name", sa.String(), nullable=True),
            sa.Column("predicted_winner", sa.String(), nullable=False),
            sa.Column("predicted_winner_label", sa.String(), nullable=True),
            sa.Column("model_prob", sa.Float(), nullable=True),
            sa.Column("market_prob", sa.Float(), nullable=True),
            sa.Column("edge", sa.Float(), nullable=True),
            sa.Column("odds", sa.Float(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("pick_score", sa.Float(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["betting_slip_id"], ["betting_slip.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "betting_slip_id",
                "event_key",
                name="uq_betting_slip_pick_event",
            ),
        )

    inspector = inspect(op.get_bind())
    pick_indexes = {index["name"] for index in inspector.get_indexes("betting_slip_pick")}
    if "ix_betting_slip_pick_betting_slip_id" not in pick_indexes:
        op.create_index(
            op.f("ix_betting_slip_pick_betting_slip_id"),
            "betting_slip_pick",
            ["betting_slip_id"],
            unique=False,
        )
    if "ix_betting_slip_pick_event_key" not in pick_indexes:
        op.create_index(
            op.f("ix_betting_slip_pick_event_key"),
            "betting_slip_pick",
            ["event_key"],
            unique=False,
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "betting_slip_pick" in tables:
        op.drop_table("betting_slip_pick")
    if "betting_slip" in tables:
        op.drop_table("betting_slip")
