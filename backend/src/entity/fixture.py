from sqlalchemy import Column, Date, Integer, String, Time
from sqlalchemy.types import JSON

from backend.src.entity.base import Base


class Fixture(Base):
    __tablename__ = "fixture"

    id_fixture = Column(Integer, primary_key=True)
    event_key = Column(Integer, unique=True, nullable=False)

    event_date = Column(Date)
    event_time = Column(Time)

    event_first_player = Column(String)
    first_player_key = Column(Integer)
    event_second_player = Column(String)
    second_player_key = Column(Integer)

    event_final_result = Column(String)
    event_game_result = Column(String)
    event_serve = Column(String)
    event_winner = Column(String)
    event_status = Column(String)

    event_type_type = Column(String)

    tournament_name = Column(String)
    tournament_key = Column(Integer)
    tournament_round = Column(String)
    tournament_season = Column(String)

    event_live = Column(String)
    event_first_player_logo = Column(String)
    event_second_player_logo = Column(String)
    event_qualification = Column(String)

    # Colonne JSON per strutture figlie annidate (pointbypoint -> points, scores, statistics,odds)
    pointbypoint = Column(JSON)
    scores = Column(JSON)
    statistics = Column(JSON)
    odds = Column(JSON(none_as_null=True))

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
