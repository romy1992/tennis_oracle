"""ml ready schema

Revision ID: 0002_ml_ready_schema
Revises: 0001_initial_schema
Create Date: 2026-06-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_ml_ready_schema"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_player",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("hand", sa.String(), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index(op.f("ix_ml_player_name"), "ml_player", ["name"], unique=False)

    op.create_table(
        "ml_tournament",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("surface", sa.String(), nullable=True),
        sa.Column("level", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index(op.f("ix_ml_tournament_name"), "ml_tournament", ["name"], unique=False)
    op.create_index(op.f("ix_ml_tournament_surface"), "ml_tournament", ["surface"], unique=False)

    op.create_table(
        "ml_match",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("tournament_id", sa.Integer(), nullable=True),
        sa.Column("match_date", sa.Date(), nullable=False),
        sa.Column("round", sa.String(), nullable=True),
        sa.Column("surface", sa.String(), nullable=True),
        sa.Column("best_of", sa.Integer(), nullable=True),
        sa.Column("player_1_id", sa.Integer(), nullable=False),
        sa.Column("player_2_id", sa.Integer(), nullable=False),
        sa.Column("winner_id", sa.Integer(), nullable=True),
        sa.Column("loser_id", sa.Integer(), nullable=True),
        sa.Column("score", sa.String(), nullable=True),
        sa.Column("player_1_rank_at_match", sa.Integer(), nullable=True),
        sa.Column("player_2_rank_at_match", sa.Integer(), nullable=True),
        sa.Column("player_1_seed", sa.Integer(), nullable=True),
        sa.Column("player_2_seed", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["loser_id"], ["ml_player.id"]),
        sa.ForeignKeyConstraint(["player_1_id"], ["ml_player.id"]),
        sa.ForeignKeyConstraint(["player_2_id"], ["ml_player.id"]),
        sa.ForeignKeyConstraint(["tournament_id"], ["ml_tournament.id"]),
        sa.ForeignKeyConstraint(["winner_id"], ["ml_player.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index(op.f("ix_ml_match_loser_id"), "ml_match", ["loser_id"], unique=False)
    op.create_index(op.f("ix_ml_match_match_date"), "ml_match", ["match_date"], unique=False)
    op.create_index(op.f("ix_ml_match_player_1_id"), "ml_match", ["player_1_id"], unique=False)
    op.create_index(op.f("ix_ml_match_player_2_id"), "ml_match", ["player_2_id"], unique=False)
    op.create_index(op.f("ix_ml_match_surface"), "ml_match", ["surface"], unique=False)
    op.create_index(op.f("ix_ml_match_tournament_id"), "ml_match", ["tournament_id"], unique=False)
    op.create_index(op.f("ix_ml_match_winner_id"), "ml_match", ["winner_id"], unique=False)

    op.create_table(
        "ranking_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("ranking_date", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("tour", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["ml_player.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "ranking_date", "tour", name="uq_ranking_player_date_tour"),
    )
    op.create_index(op.f("ix_ranking_snapshot_player_id"), "ranking_snapshot", ["player_id"], unique=False)
    op.create_index(op.f("ix_ranking_snapshot_ranking_date"), "ranking_snapshot", ["ranking_date"], unique=False)

    op.create_table(
        "odds_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("bookmaker", sa.String(), nullable=True),
        sa.Column("player_1_odds", sa.Float(), nullable=True),
        sa.Column("player_2_odds", sa.Float(), nullable=True),
        sa.Column("implied_prob_player_1", sa.Float(), nullable=True),
        sa.Column("implied_prob_player_2", sa.Float(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["ml_match.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_odds_snapshot_captured_at"), "odds_snapshot", ["captured_at"], unique=False)
    op.create_index(op.f("ix_odds_snapshot_match_id"), "odds_snapshot", ["match_id"], unique=False)

    op.create_table(
        "feature_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("player_1_id", sa.Integer(), nullable=False),
        sa.Column("player_2_id", sa.Integer(), nullable=False),
        sa.Column("feature_date", sa.Date(), nullable=False),
        sa.Column("surface", sa.String(), nullable=True),
        sa.Column("player_1_rank", sa.Integer(), nullable=True),
        sa.Column("player_2_rank", sa.Integer(), nullable=True),
        sa.Column("rank_diff", sa.Integer(), nullable=True),
        sa.Column("player_1_elo", sa.Float(), nullable=True),
        sa.Column("player_2_elo", sa.Float(), nullable=True),
        sa.Column("elo_diff", sa.Float(), nullable=True),
        sa.Column("player_1_surface_elo", sa.Float(), nullable=True),
        sa.Column("player_2_surface_elo", sa.Float(), nullable=True),
        sa.Column("surface_elo_diff", sa.Float(), nullable=True),
        sa.Column("player_1_last_5_win_rate", sa.Float(), nullable=True),
        sa.Column("player_2_last_5_win_rate", sa.Float(), nullable=True),
        sa.Column("player_1_last_10_win_rate", sa.Float(), nullable=True),
        sa.Column("player_2_last_10_win_rate", sa.Float(), nullable=True),
        sa.Column("player_1_surface_last_10_win_rate", sa.Float(), nullable=True),
        sa.Column("player_2_surface_last_10_win_rate", sa.Float(), nullable=True),
        sa.Column("player_1_matches_last_14_days", sa.Integer(), nullable=True),
        sa.Column("player_2_matches_last_14_days", sa.Integer(), nullable=True),
        sa.Column("player_1_days_since_last_match", sa.Integer(), nullable=True),
        sa.Column("player_2_days_since_last_match", sa.Integer(), nullable=True),
        sa.Column("h2h_player_1_wins", sa.Integer(), nullable=True),
        sa.Column("h2h_player_2_wins", sa.Integer(), nullable=True),
        sa.Column("h2h_surface_player_1_wins", sa.Integer(), nullable=True),
        sa.Column("h2h_surface_player_2_wins", sa.Integer(), nullable=True),
        sa.Column("target_player_1_win", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["ml_match.id"]),
        sa.ForeignKeyConstraint(["player_1_id"], ["ml_player.id"]),
        sa.ForeignKeyConstraint(["player_2_id"], ["ml_player.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", name="uq_feature_snapshot_match"),
    )
    op.create_index(op.f("ix_feature_snapshot_feature_date"), "feature_snapshot", ["feature_date"], unique=False)
    op.create_index(op.f("ix_feature_snapshot_match_id"), "feature_snapshot", ["match_id"], unique=False)
    op.create_index(op.f("ix_feature_snapshot_player_1_id"), "feature_snapshot", ["player_1_id"], unique=False)
    op.create_index(op.f("ix_feature_snapshot_player_2_id"), "feature_snapshot", ["player_2_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_feature_snapshot_player_2_id"), table_name="feature_snapshot")
    op.drop_index(op.f("ix_feature_snapshot_player_1_id"), table_name="feature_snapshot")
    op.drop_index(op.f("ix_feature_snapshot_match_id"), table_name="feature_snapshot")
    op.drop_index(op.f("ix_feature_snapshot_feature_date"), table_name="feature_snapshot")
    op.drop_table("feature_snapshot")
    op.drop_index(op.f("ix_odds_snapshot_match_id"), table_name="odds_snapshot")
    op.drop_index(op.f("ix_odds_snapshot_captured_at"), table_name="odds_snapshot")
    op.drop_table("odds_snapshot")
    op.drop_index(op.f("ix_ranking_snapshot_ranking_date"), table_name="ranking_snapshot")
    op.drop_index(op.f("ix_ranking_snapshot_player_id"), table_name="ranking_snapshot")
    op.drop_table("ranking_snapshot")
    op.drop_index(op.f("ix_ml_match_winner_id"), table_name="ml_match")
    op.drop_index(op.f("ix_ml_match_tournament_id"), table_name="ml_match")
    op.drop_index(op.f("ix_ml_match_surface"), table_name="ml_match")
    op.drop_index(op.f("ix_ml_match_player_2_id"), table_name="ml_match")
    op.drop_index(op.f("ix_ml_match_player_1_id"), table_name="ml_match")
    op.drop_index(op.f("ix_ml_match_match_date"), table_name="ml_match")
    op.drop_index(op.f("ix_ml_match_loser_id"), table_name="ml_match")
    op.drop_table("ml_match")
    op.drop_index(op.f("ix_ml_tournament_surface"), table_name="ml_tournament")
    op.drop_index(op.f("ix_ml_tournament_name"), table_name="ml_tournament")
    op.drop_table("ml_tournament")
    op.drop_index(op.f("ix_ml_player_name"), table_name="ml_player")
    op.drop_table("ml_player")
