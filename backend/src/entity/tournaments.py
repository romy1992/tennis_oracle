from sqlalchemy import Column, Integer, String
from src.entity.base import Base

class Tournament(Base):
    __tablename__ = 'tournament'
    id_tournament = Column(Integer, primary_key=True)
    tournament_key = Column(Integer, unique=True)
    tournament_name = Column(String)
    event_type_key = Column(Integer)
    event_type_type = Column(String)
    tournament_sourface = Column(String)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
