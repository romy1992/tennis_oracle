import unittest
from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.app.db.session import get_db
from backend.src.app.main import app
from backend.src.app.services.single_match_value import (
    calculate_expected_roi,
    calculate_void_odds,
    classify_single_bet_value,
)
from backend.src.entity import Fixture, MatchPrediction, NextFixture
from backend.src.entity.base import Base


class SingleMatchValueTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        def override_get_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_void_odds_and_expected_roi_formula(self):
        self.assertAlmostEqual(calculate_void_odds(0.833333), 1.2, places=4)
        self.assertAlmostEqual(calculate_expected_roi(1.25, 0.833333), 0.04166625)

    def test_classifies_play_no_bet_and_borderline(self):
        void_odds = calculate_void_odds(0.72)

        self.assertEqual(
            classify_single_bet_value(
                market_odds=1.52,
                void_odds=void_odds,
                min_edge_percent=3.0,
            ),
            "PLAY",
        )
        self.assertEqual(
            classify_single_bet_value(
                market_odds=1.42,
                void_odds=void_odds,
                min_edge_percent=3.0,
            ),
            "BORDERLINE",
        )
        self.assertEqual(
            classify_single_bet_value(
                market_odds=1.30,
                void_odds=void_odds,
                min_edge_percent=3.0,
            ),
            "NO BET",
        )

    def test_route_returns_single_match_value_analysis(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    NextFixture(
                        event_key=100,
                        event_date=today,
                        event_first_player="Sinner",
                        event_second_player="Alcaraz",
                        tournament_name="Demo Open",
                        odds={
                            "100": {
                                "Home/Away": {
                                    "Home": {"Book A": "1.52"},
                                    "Away": {"Book A": "2.80"},
                                }
                            }
                        },
                        is_completed=False,
                    ),
                    MatchPrediction(
                        event_key=100,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.72,
                        predicted_winner="First Player",
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/single-match-value",
            params={"model_version": "v2", "model_name": "random_forest"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        item = payload["items"][0]
        self.assertEqual(item["match_id"], 100)
        self.assertEqual(item["selection"], "Sinner")
        self.assertEqual(item["decision"], "PLAY")
        self.assertAlmostEqual(item["void_odds"], 1.3889, places=4)
        self.assertAlmostEqual(item["expected_roi"], 0.0944, places=4)
        self.assertEqual(item["value_label"], "Singola con valore")

    def test_route_prepares_historical_simulation_for_play_bets(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    Fixture(
                        id_fixture=200,
                        event_key=200,
                        event_date=today,
                        event_first_player="Djokovic",
                        event_second_player="Rune",
                        tournament_name="Demo Open",
                        event_winner="First Player",
                        odds={
                            "200": {
                                "Home/Away": {
                                    "Home": {"Book A": "1.52"},
                                    "Away": {"Book A": "2.80"},
                                }
                            }
                        },
                    ),
                    MatchPrediction(
                        event_key=200,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.72,
                        predicted_winner="First Player",
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/single-match-value",
            params={
                "model_version": "v2",
                "model_name": "random_forest",
                "status": "played",
            },
        )

        self.assertEqual(response.status_code, 200)
        simulation = response.json()["simulation"]["play_bets"]
        self.assertEqual(simulation["bets_count"], 1)
        self.assertEqual(simulation["resolved_count"], 1)
        self.assertAlmostEqual(simulation["profit_loss_units"], 0.52)
        self.assertAlmostEqual(simulation["roi_pct"], 52.0)
        self.assertAlmostEqual(simulation["hit_rate_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
