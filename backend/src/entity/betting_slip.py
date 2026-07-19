from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.src.entity.base import Base


class BettingSlip(Base):
    """Persisted daily betting slip (schedina)."""

    __tablename__ = "betting_slip"
    __table_args__ = (
        UniqueConstraint(
            "slip_date",
            "slip_key",
            "model_version",
            "model_name",
            name="uq_betting_slip_date_key_model",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    slip_date = Column(Date, nullable=False, index=True)
    slip_key = Column(String, nullable=False)
    label = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    model_version = Column(String, nullable=False)
    model_name = Column(String, nullable=False)
    pick_count = Column(Integer, nullable=False)
    combined_odds = Column(Float, nullable=False)
    generated_at = Column(DateTime, nullable=False)

    picks = relationship(
        "BettingSlipPick",
        back_populates="betting_slip",
        cascade="all, delete-orphan",
        order_by="BettingSlipPick.sort_order",
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class BettingSlipDay(Base):
    """Daily registry for betting slip calendar and generation history."""

    __tablename__ = "betting_slip_day"
    __table_args__ = (
        UniqueConstraint(
            "slip_date",
            "model_version",
            "model_name",
            name="uq_betting_slip_day_date_model",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    slip_date = Column(Date, nullable=False, index=True)
    model_version = Column(String, nullable=False)
    model_name = Column(String, nullable=False)
    candidate_pool_size = Column(Integer, nullable=False, default=0)
    slip_count = Column(Integer, nullable=False, default=0)
    fixture_count = Column(Integer, nullable=False, default=0)
    generated_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class BettingSlipPick(Base):
    """Single pick within a persisted betting slip."""

    __tablename__ = "betting_slip_pick"
    __table_args__ = (
        UniqueConstraint(
            "betting_slip_id",
            "event_key",
            name="uq_betting_slip_pick_event",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    betting_slip_id = Column(Integer, ForeignKey("betting_slip.id"), nullable=False, index=True)
    event_key = Column(Integer, nullable=False, index=True)
    event_date = Column(Date, nullable=True)
    event_time = Column(Time, nullable=True)
    tournament_name = Column(String, nullable=True)
    surface = Column(String, nullable=True)
    player_1_name = Column(String, nullable=True)
    player_2_name = Column(String, nullable=True)
    predicted_winner = Column(String, nullable=False)
    predicted_winner_label = Column(String, nullable=True)
    model_prob = Column(Float, nullable=True)
    market_prob = Column(Float, nullable=True)
    edge = Column(Float, nullable=True)
    odds = Column(Float, nullable=True)
    void_odds = Column(Float, nullable=True)
    edge_absolute = Column(Float, nullable=True)
    edge_percent = Column(Float, nullable=True)
    expected_roi = Column(Float, nullable=True)
    suggested_min_edge_percent = Column(Float, nullable=True)
    min_edge_percent = Column(Float, nullable=True)
    value_decision = Column(String, nullable=True)
    value_label = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    pick_score = Column(Float, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)

    betting_slip = relationship("BettingSlip", back_populates="picks")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
