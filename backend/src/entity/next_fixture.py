from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, Time
from sqlalchemy.types import JSON

from backend.src.entity.base import Base


class NextFixture(Base):
    """Rolling snapshot of upcoming fixtures (typically today through +7 days)."""

    __tablename__ = "next_fixture"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_key = Column(Integer, unique=True, nullable=False)

    event_date = Column(Date)
    event_time = Column(Time)

    event_first_player = Column(String)
    first_player_key = Column(Integer)
    event_second_player = Column(String)
    second_player_key = Column(Integer)

    tournament_name = Column(String)
    tournament_key = Column(Integer)
    tournament_round = Column(String)
    surface = Column(String)

    event_status = Column(String)
    event_type_type = Column(String)

    odds = Column(JSON)

    imported_at = Column(DateTime)
    week_start = Column(Date)
    week_end = Column(Date)

    source = Column(String, default="api-tennis")

    is_completed = Column(Boolean, default=False)
    moved_to_fixture_at = Column(DateTime)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
