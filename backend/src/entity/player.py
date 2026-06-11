from sqlalchemy import Column, Integer, String
from sqlalchemy.types import JSON

from src.entity.base import Base


class Player(Base):
    __tablename__ = "player"

    id_player = Column(Integer, primary_key=True)
    player_key = Column(Integer, unique=True, nullable=False)
    player_name = Column(String)
    player_full_name = Column(String)
    player_country = Column(String)
    player_bday = Column(String)
    player_logo = Column(String)

    # Strutture figlie annidate
    stats = Column(JSON)
    tournaments = Column(JSON)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
