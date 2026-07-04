from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.models import Fixture


def list_matches(db: Session, limit: int = 100, offset: int = 0) -> list[Fixture]:
    stmt = (
        select(Fixture)
        .order_by(Fixture.event_date.desc().nullslast(), Fixture.id_fixture.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def get_match(db: Session, match_id: int) -> Fixture | None:
    return db.get(Fixture, match_id)
