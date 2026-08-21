"""stable daily slip pool, live score and persisted pick outcome

Revision ID: 0032_daily_slip_lifecycle
Revises: 0031_widen_wf_versions
Create Date: 2026-08-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0032_daily_slip_lifecycle"
down_revision: Union[str, None] = "0031_widen_wf_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "next_fixture" in tables:
        columns = {column["name"] for column in inspector.get_columns("next_fixture")}
        with op.batch_alter_table("next_fixture") as batch_op:
            if "event_winner" not in columns:
                batch_op.add_column(sa.Column("event_winner", sa.String(), nullable=True))
            if "event_live" not in columns:
                batch_op.add_column(sa.Column("event_live", sa.String(), nullable=True))
            if "live_score" not in columns:
                batch_op.add_column(sa.Column("live_score", sa.JSON(), nullable=True))
            if "live_score_updated_at" not in columns:
                batch_op.add_column(
                    sa.Column("live_score_updated_at", sa.DateTime(), nullable=True)
                )

    if "betting_slip_pick" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("betting_slip_pick")
        }
        constraints = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("betting_slip_pick")
        }
        with op.batch_alter_table("betting_slip_pick") as batch_op:
            if "outcome" not in columns:
                batch_op.add_column(
                    sa.Column(
                        "outcome",
                        sa.String(),
                        nullable=False,
                        server_default="pending",
                    )
                )
            if "settled_at" not in columns:
                batch_op.add_column(sa.Column("settled_at", sa.DateTime(), nullable=True))
            if "ck_betting_slip_pick_outcome" not in constraints:
                batch_op.create_check_constraint(
                    "ck_betting_slip_pick_outcome",
                    "outcome IN ('pending', 'won', 'lost', 'void')",
                )

    if "betting_slip_day" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("betting_slip_day")
        }
        with op.batch_alter_table("betting_slip_day") as batch_op:
            if "pool_closes_at" not in columns:
                batch_op.add_column(
                    sa.Column("pool_closes_at", sa.DateTime(), nullable=True)
                )
            if "pool_locked_at" not in columns:
                batch_op.add_column(
                    sa.Column("pool_locked_at", sa.DateTime(), nullable=True)
                )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "betting_slip_day" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("betting_slip_day")
        }
        with op.batch_alter_table("betting_slip_day") as batch_op:
            if "pool_locked_at" in columns:
                batch_op.drop_column("pool_locked_at")
            if "pool_closes_at" in columns:
                batch_op.drop_column("pool_closes_at")

    if "betting_slip_pick" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("betting_slip_pick")
        }
        constraints = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("betting_slip_pick")
        }
        with op.batch_alter_table("betting_slip_pick") as batch_op:
            if "ck_betting_slip_pick_outcome" in constraints:
                batch_op.drop_constraint(
                    "ck_betting_slip_pick_outcome", type_="check"
                )
            if "settled_at" in columns:
                batch_op.drop_column("settled_at")
            if "outcome" in columns:
                batch_op.drop_column("outcome")

    if "next_fixture" in tables:
        columns = {column["name"] for column in inspector.get_columns("next_fixture")}
        with op.batch_alter_table("next_fixture") as batch_op:
            if "live_score_updated_at" in columns:
                batch_op.drop_column("live_score_updated_at")
            if "live_score" in columns:
                batch_op.drop_column("live_score")
            if "event_live" in columns:
                batch_op.drop_column("event_live")
            if "event_winner" in columns:
                batch_op.drop_column("event_winner")
