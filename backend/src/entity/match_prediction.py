from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, UniqueConstraint

from backend.src.entity.base import Base


class MatchPrediction(Base):
    """Stored ML predictions for upcoming/completed fixtures."""

    __tablename__ = "match_prediction"
    __table_args__ = (
        UniqueConstraint(
            "event_key",
            "model_version",
            "model_name",
            name="uq_match_prediction_event_version_model",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_key = Column(Integer, nullable=False)
    model_version = Column(String, nullable=False)
    model_name = Column(String, nullable=False, default="logistic_regression")
    predicted_at = Column(DateTime, nullable=False)
    prob_player_1_win = Column(Float)
    predicted_winner = Column(String)
    actual_winner = Column(String)
    is_correct = Column(Boolean)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
