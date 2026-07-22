"""Immutable ledger of published tip/prediction snapshots.

``MatchPrediction`` remains the working ML upsert; ``BettingSlip*`` remains the
daily slip product. This table is append-only: corrections insert a new row
linked via ``previous_version_id`` / ``publication_id`` + ``content_version``.
"""

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.src.entity.base import Base


class PublishedPrediction(Base):
    """One immutable published tip snapshot (versioned via publication_id)."""

    __tablename__ = "published_prediction"
    __table_args__ = (
        UniqueConstraint(
            "publication_id",
            "content_version",
            name="uq_published_prediction_publication_version",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    publication_id = Column(String(36), nullable=False, index=True)
    content_version = Column(Integer, nullable=False, default=1)
    previous_version_id = Column(
        Integer,
        ForeignKey("published_prediction.id"),
        nullable=True,
        index=True,
    )

    event_key = Column(Integer, nullable=False, index=True)
    selection = Column(String, nullable=False)
    model_version = Column(String, nullable=False)
    model_name = Column(String, nullable=False)
    probability = Column(Float, nullable=False)
    odds = Column(Float, nullable=True)
    void_odds = Column(Float, nullable=True)
    edge = Column(Float, nullable=True)
    unit_stake = Column(Float, nullable=False)
    published_at = Column(DateTime, nullable=False, index=True)
    publication_source = Column(String, nullable=False)
    initial_status = Column(String, nullable=False)
    content_hash = Column(String(64), nullable=False)

    # Optional display / lineage (denormalized; not a substitute for MatchPrediction)
    player_1_name = Column(String, nullable=True)
    player_2_name = Column(String, nullable=True)
    tournament_name = Column(String, nullable=True)
    event_date = Column(Date, nullable=True)
    event_time = Column(Time, nullable=True)
    match_prediction_id = Column(Integer, nullable=True, index=True)
    betting_slip_pick_id = Column(Integer, nullable=True, index=True)

    previous_version = relationship(
        "PublishedPrediction",
        remote_side=[id],
        foreign_keys=[previous_version_id],
        uselist=False,
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
