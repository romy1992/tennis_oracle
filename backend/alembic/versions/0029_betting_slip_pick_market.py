"""betting slip pick market column (mixed-market slips)

Adds ``market`` to ``betting_slip_pick`` so a single slip can mix picks from
different markets (match_winner, over_under_games) on the SAME fixture: the
previous unique constraint was (betting_slip_id, event_key), which physically
forbade two picks on the same match within one slip. Replaced with
(betting_slip_id, event_key, market).

Revision ID: 0029_betting_slip_pick_market
Revises: 0028_feature_flags
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0029_betting_slip_pick_market"
down_revision: Union[str, None] = "0028_feature_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_MARKET = "match_winner"
OLD_CONSTRAINT = "uq_betting_slip_pick_event"
NEW_CONSTRAINT = "uq_betting_slip_pick_event_market"


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "betting_slip_pick" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("betting_slip_pick")}
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("betting_slip_pick")
    }

    if "market" not in columns:
        with op.batch_alter_table("betting_slip_pick") as batch_op:
            batch_op.add_column(
                sa.Column("market", sa.String(), nullable=False, server_default=DEFAULT_MARKET)
            )

    if OLD_CONSTRAINT in unique_constraints:
        with op.batch_alter_table("betting_slip_pick") as batch_op:
            batch_op.drop_constraint(OLD_CONSTRAINT, type_="unique")

    if NEW_CONSTRAINT not in unique_constraints:
        with op.batch_alter_table("betting_slip_pick") as batch_op:
            batch_op.create_unique_constraint(
                NEW_CONSTRAINT, ["betting_slip_id", "event_key", "market"]
            )

    with op.batch_alter_table("betting_slip_pick") as batch_op:
        batch_op.alter_column("market", server_default=None)


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "betting_slip_pick" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("betting_slip_pick")}
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("betting_slip_pick")
    }

    with op.batch_alter_table("betting_slip_pick") as batch_op:
        if NEW_CONSTRAINT in unique_constraints:
            batch_op.drop_constraint(NEW_CONSTRAINT, type_="unique")
        if OLD_CONSTRAINT not in unique_constraints:
            batch_op.create_unique_constraint(OLD_CONSTRAINT, ["betting_slip_id", "event_key"])
        if "market" in columns:
            batch_op.drop_column("market")

