"""multi-market columns for publication and odds ledgers

Revision ID: 0030_multi_market_columns
Revises: 0029_betting_slip_pick_market
Create Date: 2026-08-14

Adds explicit market metadata to the immutable publication and pre-match odds
ledgers. Existing publications are classified from ``model_version``; existing
odds snapshots remain match-winner observations.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0030_multi_market_columns"
down_revision: Union[str, None] = "0029_betting_slip_pick_market"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_MARKET = "match_winner"


def _backfill_published_predictions() -> None:
    op.execute(
        sa.text(
            "UPDATE published_prediction "
            "SET market = CASE "
            "WHEN model_version = 'first_set_winner_v1' THEN 'first_set_winner' "
            "WHEN model_version = 'over_under_games_v1' THEN 'over_under_games' "
            "ELSE 'match_winner' END "
            "WHERE market IS NULL OR market = 'match_winner'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE published_prediction "
            "SET value_decision = CASE "
            "WHEN market = 'first_set_winner' THEN NULL "
            "WHEN publication_source = 'global_update' THEN 'PLAY' "
            "WHEN market = 'over_under_games' "
            "AND odds IS NOT NULL AND void_odds IS NOT NULL "
            "AND odds >= void_odds * 1.02 THEN 'PLAY' "
            "WHEN market = 'over_under_games' "
            "AND odds IS NOT NULL AND void_odds IS NOT NULL "
            "AND odds < void_odds THEN 'NO BET' "
            "WHEN market = 'over_under_games' "
            "AND odds IS NOT NULL AND void_odds IS NOT NULL THEN 'BORDERLINE' "
            "ELSE value_decision END"
        )
    )
    op.execute(
        sa.text(
            "UPDATE published_prediction "
            "SET official_play = CASE "
            "WHEN market = 'first_set_winner' THEN false "
            "WHEN publication_source = 'global_update' THEN true "
            "WHEN market = 'over_under_games' "
            "AND publication_source = 'system' "
            "AND value_decision = 'PLAY' THEN true "
            "ELSE false END"
        )
    )


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "published_prediction" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("published_prediction")
        }
        if "market" not in columns:
            op.add_column(
                "published_prediction",
                sa.Column(
                    "market",
                    sa.String(),
                    nullable=False,
                    server_default=DEFAULT_MARKET,
                ),
            )
        if "value_decision" not in columns:
            op.add_column(
                "published_prediction",
                sa.Column("value_decision", sa.String(), nullable=True),
            )
        if "official_play" not in columns:
            op.add_column(
                "published_prediction",
                sa.Column(
                    "official_play",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        _backfill_published_predictions()

    if "prematch_odds_snapshot" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("prematch_odds_snapshot")
        }
        if "market" not in columns:
            op.add_column(
                "prematch_odds_snapshot",
                sa.Column(
                    "market",
                    sa.String(),
                    nullable=False,
                    server_default=DEFAULT_MARKET,
                ),
            )
        if "market_line" not in columns:
            op.add_column(
                "prematch_odds_snapshot",
                sa.Column("market_line", sa.Float(), nullable=True),
            )
        op.execute(
            sa.text(
                "UPDATE prematch_odds_snapshot "
                "SET market = 'match_winner' WHERE market IS NULL"
            )
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "prematch_odds_snapshot" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("prematch_odds_snapshot")
        }
        with op.batch_alter_table("prematch_odds_snapshot") as batch_op:
            if "market_line" in columns:
                batch_op.drop_column("market_line")
            if "market" in columns:
                batch_op.drop_column("market")

    if "published_prediction" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("published_prediction")
        }
        with op.batch_alter_table("published_prediction") as batch_op:
            if "official_play" in columns:
                batch_op.drop_column("official_play")
            if "value_decision" in columns:
                batch_op.drop_column("value_decision")
            if "market" in columns:
                batch_op.drop_column("market")
