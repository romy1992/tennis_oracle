import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.app.services import import_state as import_state_module
from backend.src.app.services.import_state import get_import_status, record_fixture_import
from backend.src.app.services.imports import (
    _latest_played_match_date,
    purge_future_incomplete_fixtures,
)
from backend.src.entity import Fixture
from backend.src.entity.base import Base


class ImportStateDatesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self._state_path = import_state_module.STATE_PATH
        self._original_state = (
            self._state_path.read_text(encoding="utf-8")
            if self._state_path.exists()
            else None
        )

    def tearDown(self):
        if self._original_state is None:
            if self._state_path.exists():
                self._state_path.unlink()
        else:
            self._state_path.write_text(self._original_state, encoding="utf-8")
        self.engine.dispose()

    def test_latest_played_match_date_ignores_future(self):
        today = date.today()
        with self.Session() as session:
            session.add(
                Fixture(
                    id_fixture=1,
                    event_key=1,
                    event_date=today - timedelta(days=1),
                )
            )
            session.add(
                Fixture(
                    id_fixture=2,
                    event_key=2,
                    event_date=today + timedelta(days=60),
                    event_final_result="-",
                )
            )
            session.commit()
            latest = _latest_played_match_date(session)
            self.assertEqual(latest, today - timedelta(days=1))

    def test_get_import_status_overrides_future_json_last_match_date(self):
        today = date.today()
        record_fixture_import(
            last_match_date=today + timedelta(days=60),
            imported_at=datetime.now(),
            days_back_start=3,
        )
        with self.Session() as session:
            session.add(
                Fixture(
                    id_fixture=1,
                    event_key=1,
                    event_date=today - timedelta(days=2),
                )
            )
            session.commit()
            status = get_import_status(session)
        self.assertEqual(status["fixtures_last_match_date"], today - timedelta(days=2))

    def test_purge_future_incomplete_fixtures(self):
        today = date.today()
        with self.Session() as session:
            session.add(
                Fixture(
                    id_fixture=1,
                    event_key=1,
                    event_date=today + timedelta(days=30),
                    event_final_result="-",
                )
            )
            session.add(
                Fixture(
                    id_fixture=2,
                    event_key=2,
                    event_date=today - timedelta(days=1),
                    event_winner="First Player",
                    event_final_result="2 - 0",
                )
            )
            session.commit()
            removed = purge_future_incomplete_fixtures(session)
            self.assertEqual(removed, 1)
            remaining = session.query(Fixture).all()
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].event_key, 2)


if __name__ == "__main__":
    unittest.main()
