"""Append-only ledger of pre-match bookmaker odds snapshots.

Distinct from the unused ML table ``odds_snapshot`` (FK to ``ml_match``).
Operational history is keyed by ``event_key`` and never overwrites prior rows.
"""

from sqlalchemy import Column, DateTime, Float, Integer, String, UniqueConstraint

from backend.src.entity.base import Base


class PrematchOddsSnapshot(Base):
    """One detected pre-match quote (bookmaker × selection × timestamp)."""

    __tablename__ = "prematch_odds_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "detection_hash",
            name="uq_prematch_odds_snapshot_detection_hash",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_key = Column(Integer, nullable=False, index=True)
    market = Column(
        String, nullable=False, default="match_winner", server_default="match_winner"
    )
    market_line = Column(Float, nullable=True)
    selection = Column(String, nullable=False)
    bookmaker = Column(String, nullable=False)
    odds = Column(Float, nullable=False)
    implied_probability = Column(Float, nullable=False)
    margin = Column(Float, nullable=False)
    captured_at = Column(DateTime, nullable=False, index=True)
    source = Column(String, nullable=False)
    snapshot_type = Column(String, nullable=False, index=True)
    # Stable fingerprint of the detection (excludes id); enforces dedup at DB level.
    detection_hash = Column(String(64), nullable=False)
    market_side = Column(String, nullable=True)
    player_1_name = Column(String, nullable=True)
    player_2_name = Column(String, nullable=True)

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
