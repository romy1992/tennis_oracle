from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.models import Player


def list_players(db: Session, limit: int = 100, offset: int = 0) -> list[Player]:
    stmt = (
        select(Player)
        .order_by(Player.player_name.asc().nullslast(), Player.id_player.asc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def get_player(db: Session, player_id: int) -> Player | None:
    return db.get(Player, player_id)
