"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event",
        sa.Column("id_event", sa.Integer(), nullable=False),
        sa.Column("event_type_key", sa.Integer(), nullable=True),
        sa.Column("event_type_type", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id_event"),
        sa.UniqueConstraint("event_type_key"),
    )
    op.create_table(
        "tournament",
        sa.Column("id_tournament", sa.Integer(), nullable=False),
        sa.Column("tournament_key", sa.Integer(), nullable=True),
        sa.Column("tournament_name", sa.String(), nullable=True),
        sa.Column("event_type_key", sa.Integer(), nullable=True),
        sa.Column("event_type_type", sa.String(), nullable=True),
        sa.Column("tournament_sourface", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id_tournament"),
        sa.UniqueConstraint("tournament_key"),
    )
    op.create_table(
        "fixture",
        sa.Column("id_fixture", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.Integer(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("event_time", sa.Time(), nullable=True),
        sa.Column("event_first_player", sa.String(), nullable=True),
        sa.Column("first_player_key", sa.Integer(), nullable=True),
        sa.Column("event_second_player", sa.String(), nullable=True),
        sa.Column("second_player_key", sa.Integer(), nullable=True),
        sa.Column("event_final_result", sa.String(), nullable=True),
        sa.Column("event_game_result", sa.String(), nullable=True),
        sa.Column("event_serve", sa.String(), nullable=True),
        sa.Column("event_winner", sa.String(), nullable=True),
        sa.Column("event_status", sa.String(), nullable=True),
        sa.Column("event_type_type", sa.String(), nullable=True),
        sa.Column("tournament_name", sa.String(), nullable=True),
        sa.Column("tournament_key", sa.Integer(), nullable=True),
        sa.Column("tournament_round", sa.String(), nullable=True),
        sa.Column("tournament_season", sa.String(), nullable=True),
        sa.Column("event_live", sa.String(), nullable=True),
        sa.Column("event_first_player_logo", sa.String(), nullable=True),
        sa.Column("event_second_player_logo", sa.String(), nullable=True),
        sa.Column("event_qualification", sa.String(), nullable=True),
        sa.Column("pointbypoint", sa.JSON(), nullable=True),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("statistics", sa.JSON(), nullable=True),
        sa.Column("odds", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id_fixture"),
        sa.UniqueConstraint("event_key"),
    )
    op.create_table(
        "standing",
        sa.Column("id_standing", sa.Integer(), nullable=False),
        sa.Column("place", sa.Integer(), nullable=True),
        sa.Column("player", sa.String(), nullable=True),
        sa.Column("player_key", sa.Integer(), nullable=True),
        sa.Column("league", sa.String(), nullable=True),
        sa.Column("movement", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id_standing"),
        sa.UniqueConstraint(
            "player_key", "league", name="uq_standing_player_league"
        ),
    )
    op.create_table(
        "player",
        sa.Column("id_player", sa.Integer(), nullable=False),
        sa.Column("player_key", sa.Integer(), nullable=False),
        sa.Column("player_name", sa.String(), nullable=True),
        sa.Column("player_full_name", sa.String(), nullable=True),
        sa.Column("player_country", sa.String(), nullable=True),
        sa.Column("player_bday", sa.String(), nullable=True),
        sa.Column("player_logo", sa.String(), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=True),
        sa.Column("tournaments", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id_player"),
        sa.UniqueConstraint("player_key"),
    )


def downgrade() -> None:
    op.drop_table("player")
    op.drop_table("standing")
    op.drop_table("fixture")
    op.drop_table("tournament")
    op.drop_table("event")
