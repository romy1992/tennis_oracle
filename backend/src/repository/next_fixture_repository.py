from datetime import date

from sqlalchemy import and_

from backend.src.entity.next_fixture import NextFixture
from backend.src.repository.base.crud_repository import CrudRepository


class NextFixtureRepository(CrudRepository):

    def __init__(self):
        super().__init__(NextFixture)

    def search_date_range(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int | None = None,
    ) -> list[NextFixture]:
        with self.session as session:
            query = session.query(NextFixture).filter(NextFixture.is_completed.is_(False))
            if from_date is not None:
                query = query.filter(NextFixture.event_date >= from_date)
            if to_date is not None:
                query = query.filter(NextFixture.event_date <= to_date)
            query = query.order_by(
                NextFixture.event_date.asc(),
                NextFixture.event_time.asc().nullslast(),
                NextFixture.event_key.asc(),
            )
            if limit is not None:
                query = query.limit(limit)
            return query.all()

    def delete_outside_date_range(self, from_date: date, to_date: date) -> int:
        with self.session as session:
            deleted = (
                session.query(NextFixture)
                .filter(
                    and_(
                        NextFixture.is_completed.is_(False),
                        NextFixture.event_date.isnot(None),
                        ~NextFixture.event_date.between(from_date, to_date),
                    )
                )
                .delete(synchronize_session=False)
            )
            session.commit()
            return deleted

    def delete_completed(self) -> int:
        with self.session as session:
            deleted = (
                session.query(NextFixture)
                .filter(NextFixture.is_completed.is_(True))
                .delete(synchronize_session=False)
            )
            session.commit()
            return deleted
