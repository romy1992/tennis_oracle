import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.app.db.session import get_db
from backend.src.app.main import app
from backend.src.app.services.betting_slips import (
    _resolve_pick_status,
    _resolve_slip_status,
    build_candidate_pool,
    generate_slips,
    get_betting_slip_calendar,
    get_daily_betting_slips,
)
from backend.src.entity import BettingSlip, BettingSlipDay, BettingSlipPick, Fixture, MatchPrediction, NextFixture
from backend.src.entity.base import Base


def _sample_odds() -> dict:
    return {
        "100": {
            "Home/Away": {
                "Home": {"Book A": "1.50", "Book B": "1.55"},
                "Away": {"Book A": "2.60", "Book B": "2.50"},
            }
        }
    }


class BettingSlipsServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.today = date(2026, 6, 28)

    def _seed_candidates(self, session, count: int = 6, start_key: int = 100):
        rows = []
        for index in range(count):
            event_key = start_key + index
            rows.append(
                NextFixture(
                    event_key=event_key,
                    event_date=self.today,
                    event_time=time(14, index),
                    event_first_player=f"Player A{index}",
                    event_second_player=f"Player B{index}",
                    tournament_name=f"Tournament {index % 3}",
                    surface=["Hard", "Clay", "Grass"][index % 3],
                    odds=_sample_odds(),
                    is_completed=False,
                )
            )
            rows.append(
                MatchPrediction(
                    event_key=event_key,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                    prob_player_1_win=0.72 + index * 0.01,
                    predicted_winner="First Player",
                )
            )
        session.add_all(rows)
        session.commit()

    def test_build_candidate_pool_includes_missing_odds(self):
        with self.Session() as session:
            self._seed_candidates(session, count=1)
            session.add(
                NextFixture(
                    event_key=999,
                    event_date=self.today,
                    event_first_player="No Odds",
                    event_second_player="Also None",
                    is_completed=False,
                )
            )
            session.add(
                MatchPrediction(
                    event_key=999,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                    prob_player_1_win=0.8,
                    predicted_winner="First Player",
                )
            )
            session.commit()

            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            self.assertEqual(len(candidates), 2)
            by_key = {candidate.event_key: candidate for candidate in candidates}
            self.assertEqual(by_key[999].odds, None)
            self.assertEqual(by_key[100].odds, 1.525)

    def test_build_candidate_pool_includes_heavy_favorite(self):
        heavy_favorite_odds = {
            "100": {
                "Home/Away": {
                    "Home": {"Book A": "1.08", "Book B": "1.10"},
                    "Away": {"Book A": "8.00", "Book B": "7.50"},
                }
            }
        }
        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=100,
                    event_date=self.today,
                    event_time=time(14, 0),
                    event_first_player="Sinner J.",
                    event_second_player="Qualifier",
                    tournament_name="Wimbledon",
                    surface="Grass",
                    odds=heavy_favorite_odds,
                    is_completed=False,
                )
            )
            session.add(
                MatchPrediction(
                    event_key=100,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                    prob_player_1_win=0.92,
                    predicted_winner="First Player",
                )
            )
            session.commit()

            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            self.assertEqual(len(candidates), 1)
            self.assertLess(candidates[0].odds, 1.30)

    def test_generate_slips_avoids_duplicate_event_keys(self):
        with self.Session() as session:
            self._seed_candidates(session, count=8)
            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            slips, _warnings = generate_slips(candidates)
            for slip in slips:
                keys = [pick.event_key for pick in slip.picks]
                self.assertEqual(len(keys), len(set(keys)))

    def test_persisted_slips_are_stable_on_second_load(self):
        with self.Session() as session:
            self._seed_candidates(session, count=8)
            first = get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            second = get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            first_keys = [
                (slip.slip_key, [pick.event_key for pick in slip.picks])
                for slip in first.slips
            ]
            second_keys = [
                (slip.slip_key, [pick.event_key for pick in slip.picks])
                for slip in second.slips
            ]
            self.assertEqual(first_keys, second_keys)

    def test_pick_and_slip_status_resolution(self):
        pick = BettingSlipPick(
            betting_slip_id=1,
            event_key=1,
            predicted_winner="First Player",
            sort_order=0,
        )
        self.assertEqual(_resolve_pick_status(pick, "First Player"), ("won", True))
        self.assertEqual(_resolve_pick_status(pick, "Second Player"), ("lost", False))
        self.assertEqual(_resolve_pick_status(pick, None), ("pending", None))
        self.assertEqual(_resolve_slip_status(["won", "pending"]), "pending")
        self.assertEqual(_resolve_slip_status(["won", "lost"]), "lost")
        self.assertEqual(_resolve_slip_status(["won", "won"]), "won")

    def test_calendar_includes_history_and_upcoming_window(self):
        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=500,
                    event_date=self.today + timedelta(days=3),
                    event_first_player="A",
                    event_second_player="B",
                    is_completed=False,
                )
            )
            session.add(
                NextFixture(
                    event_key=501,
                    event_date=self.today - timedelta(days=2),
                    event_first_player="C",
                    event_second_player="D",
                    odds=_sample_odds(),
                    is_completed=False,
                )
            )
            session.commit()
            self._seed_candidates(session, count=6)
            get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            calendar = get_betting_slip_calendar(
                session,
                model_version="v2",
                model_name="random_forest",
            )
            dates = [day.date for day in calendar.days]
            self.assertIn(self.today, dates)
            self.assertIn(self.today + timedelta(days=3), dates)
            self.assertGreaterEqual(calendar.window_to, self.today + timedelta(days=3))
            slip_day = session.scalar(
                select(BettingSlipDay).where(BettingSlipDay.slip_date == self.today)
            )
            self.assertIsNotNone(slip_day)
            self.assertGreater(slip_day.slip_count, 0)


class BettingSlipsRoutesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.today = date(2026, 6, 28)

        def override_get_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()

    def _seed_slip_with_pick(self, session):
        session.add(
            NextFixture(
                event_key=200,
                event_date=self.today,
                event_first_player="Sinner J.",
                event_second_player="Alcaraz C.",
                tournament_name="Wimbledon",
                surface="Grass",
                odds=_sample_odds(),
                is_completed=False,
            )
        )
        session.add(
            MatchPrediction(
                event_key=200,
                model_version="v2",
                model_name="random_forest",
                predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                prob_player_1_win=0.74,
                predicted_winner="First Player",
            )
        )
        slip = BettingSlip(
            slip_date=self.today,
            slip_key="safe",
            label="Sicura",
            description="Test",
            model_version="v2",
            model_name="random_forest",
            pick_count=1,
            combined_odds=1.52,
            generated_at=datetime(2026, 6, 28, 9, 0, 0),
        )
        session.add(slip)
        session.flush()
        session.add(
            BettingSlipPick(
                betting_slip_id=slip.id,
                event_key=200,
                event_date=self.today,
                event_time=time(14, 30),
                tournament_name="Wimbledon",
                surface="Grass",
                player_1_name="Sinner J.",
                player_2_name="Alcaraz C.",
                predicted_winner="First Player",
                predicted_winner_label="Sinner J.",
                model_prob=0.74,
                market_prob=0.65,
                edge=0.09,
                odds=1.52,
                confidence=0.74,
                pick_score=0.5,
                sort_order=0,
            )
        )
        session.commit()

    def test_daily_route_returns_persisted_slip_with_pending_pick(self):
        with self.Session() as session:
            self._seed_slip_with_pick(session)

        response = self.client.get(
            "/api/betting-slips/daily",
            params={"date": self.today.isoformat(), "model_name": "random_forest"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["slips"]), 1)
        pick = payload["slips"][0]["picks"][0]
        self.assertEqual(pick["pick_status"], "pending")
        self.assertIsNone(pick["is_correct"])

    def test_daily_route_resolves_pick_from_fixture(self):
        with self.Session() as session:
            self._seed_slip_with_pick(session)
            session.add(
                Fixture(
                    id_fixture=1,
                    event_key=200,
                    event_date=self.today,
                    event_first_player="Sinner J.",
                    event_second_player="Alcaraz C.",
                    event_winner="First Player",
                )
            )
            session.commit()

        response = self.client.get(
            "/api/betting-slips/daily",
            params={"date": self.today.isoformat(), "model_name": "random_forest"},
        )
        self.assertEqual(response.status_code, 200)
        slip = response.json()["slips"][0]
        self.assertEqual(slip["slip_status"], "won")
        self.assertEqual(slip["picks"][0]["pick_status"], "won")
        self.assertTrue(slip["picks"][0]["is_correct"])

    @patch("backend.src.app.services.imports.refresh_matches")
    @patch("backend.src.app.services.imports.import_played_fixtures")
    def test_refresh_route_does_not_duplicate_slips(self, mock_import, mock_refresh):
        mock_import.return_value = {"import_status": {}}
        mock_refresh.return_value = {"next_fixtures_imported": False}
        with self.Session() as session:
            self._seed_slip_with_pick(session)

        first = self.client.get(
            "/api/betting-slips/daily",
            params={"date": self.today.isoformat(), "model_name": "random_forest"},
        )
        refresh = self.client.post(
            "/api/betting-slips/refresh",
            params={"date": self.today.isoformat(), "model_name": "random_forest"},
        )
        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(len(refresh.json()["slips"]), len(first.json()["slips"]))

    def test_calendar_route_returns_upcoming_window(self):
        today = date.today()
        tomorrow = today + timedelta(days=1)
        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=600,
                    event_date=tomorrow,
                    event_first_player="A",
                    event_second_player="B",
                    is_completed=False,
                )
            )
            session.commit()

        response = self.client.get(
            "/api/betting-slips/calendar",
            params={"model_name": "random_forest"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        dates = [day["date"] for day in payload["days"]]
        self.assertIn(today.isoformat(), dates)
        self.assertIn(tomorrow.isoformat(), dates)


if __name__ == "__main__":
    unittest.main()
