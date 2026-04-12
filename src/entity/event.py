from sqlalchemy import Column, Integer, String
from src.entity.base import Base


class Event(Base):
    __tablename__ = "event"
    id_event = Column(Integer, primary_key=True)
    event_type_key = Column(Integer, unique=True)
    event_type_type = Column(String)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

