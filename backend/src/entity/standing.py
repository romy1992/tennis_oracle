from sqlalchemy import Column, Integer, String, UniqueConstraint

from backend.src.entity.base import Base


class Standing(Base):
    __tablename__ = "standing"
    __table_args__ = (
        UniqueConstraint("player_key", "league", name="uq_standing_player_league"),
    )

    id_standing = Column(Integer, primary_key=True)
    place = Column(Integer)
    player = Column(String)
    player_key = Column(Integer)
    league = Column(String)
    movement = Column(String)
    country = Column(String)
    points = Column(Integer)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
