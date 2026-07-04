from datetime import date, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Date,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.src.entity.base import Base


class MLPlayer(Base):
    __tablename__ = "ml_player"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    hand: Mapped[str | None] = mapped_column(String, nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MLTournament(Base):
    __tablename__ = "ml_tournament"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    surface: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    level: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MLMatch(Base):
    __tablename__ = "ml_match"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    tournament_id: Mapped[int | None] = mapped_column(
        ForeignKey("ml_tournament.id"),
        nullable=True,
        index=True,
    )
    match_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    round: Mapped[str | None] = mapped_column(String, nullable=True)
    surface: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    best_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_1_id: Mapped[int] = mapped_column(ForeignKey("ml_player.id"), nullable=False, index=True)
    player_2_id: Mapped[int] = mapped_column(ForeignKey("ml_player.id"), nullable=False, index=True)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("ml_player.id"), nullable=True, index=True)
    loser_id: Mapped[int | None] = mapped_column(ForeignKey("ml_player.id"), nullable=True, index=True)
    score: Mapped[str | None] = mapped_column(String, nullable=True)
    player_1_rank_at_match: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_2_rank_at_match: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_1_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_2_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    tournament = relationship("MLTournament")
    player_1 = relationship("MLPlayer", foreign_keys=[player_1_id])
    player_2 = relationship("MLPlayer", foreign_keys=[player_2_id])
    winner = relationship("MLPlayer", foreign_keys=[winner_id])
    loser = relationship("MLPlayer", foreign_keys=[loser_id])


class RankingSnapshot(Base):
    __tablename__ = "ranking_snapshot"
    __table_args__ = (
        UniqueConstraint("player_id", "ranking_date", "tour", name="uq_ranking_player_date_tour"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("ml_player.id"), nullable=False, index=True)
    ranking_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tour: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    player = relationship("MLPlayer")


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("ml_match.id"), nullable=False, index=True)
    bookmaker: Mapped[str | None] = mapped_column(String, nullable=True)
    player_1_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_2_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    implied_prob_player_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    implied_prob_player_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    match = relationship("MLMatch")


class FeatureSnapshot(Base):
    __tablename__ = "feature_snapshot"
    __table_args__ = (
        UniqueConstraint("match_id", name="uq_feature_snapshot_match"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("ml_match.id"), nullable=False, index=True)
    player_1_id: Mapped[int] = mapped_column(ForeignKey("ml_player.id"), nullable=False, index=True)
    player_2_id: Mapped[int] = mapped_column(ForeignKey("ml_player.id"), nullable=False, index=True)
    feature_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    surface: Mapped[str | None] = mapped_column(String, nullable=True)
    player_1_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_2_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank_diff: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_1_elo: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_2_elo: Mapped[float | None] = mapped_column(Float, nullable=True)
    elo_diff: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_1_surface_elo: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_2_surface_elo: Mapped[float | None] = mapped_column(Float, nullable=True)
    surface_elo_diff: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_1_last_5_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_2_last_5_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_1_last_10_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_2_last_10_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_1_surface_last_10_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_2_surface_last_10_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_1_matches_last_14_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_2_matches_last_14_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_1_days_since_last_match: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_2_days_since_last_match: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h2h_player_1_wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h2h_player_2_wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h2h_surface_player_1_wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h2h_surface_player_2_wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_player_1_win: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    match = relationship("MLMatch")
    player_1 = relationship("MLPlayer", foreign_keys=[player_1_id])
    player_2 = relationship("MLPlayer", foreign_keys=[player_2_id])
