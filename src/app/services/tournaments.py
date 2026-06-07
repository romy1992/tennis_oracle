from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.models import Tournament


def list_tournaments(
    db: Session,
    limit: int = 100,
    offset: int = 0,
) -> list[Tournament]:
    stmt = (
        select(Tournament)
        .order_by(Tournament.tournament_name.asc().nullslast())
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())
