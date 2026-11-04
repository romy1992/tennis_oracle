import unittest
from datetime import date, datetime

from fastapi.testclient import TestClient

from backend.src.app.main import app
from backend.src.app.services.single_match_value import (
    calculate_expected_roi,
    calculate_match_min_edge_percent,
    calculate_void_odds,
    classify_single_bet_value,
)
from backend.src.entity import Fixture, MatchPrediction, NextFixture
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client
from backend.tests.auth_helpers import clear_settings_override, make_test_settings, override_settings


class BlendWithMarketTest(unittest.TestCase):
    def test_blend_uses_market_weight(self):
        from backend.src.app.services.single_match_value import blend_with_market

        self.assertAlmostEqual(
            blend_with_market(0.80, 0.60, market="over_under_games"), 0.70, places=6
        )
        self.assertAlmostEqual(
            blend_with_market(0.80, 0.60, market="first_set_winner"), 0.75, places=6
        )

    def test_weight_one_keeps_model_probability(self):
        from backend.src.app.services.single_match_value import blend_with_market

        self.assertEqual(blend_with_market(0.80, None, model_weight=1.0), 0.80)

    def test_missing_market_probability_returns_none(self):
        from backend.src.app.services.single_match_value import blend_with_market

        self.assertIsNone(blend_with_market(0.80, None, market="over_under_games"))
        self.assertIsNone(blend_with_market(0.80, 1.2, market="over_under_games"))

    def test_invalid_weight_raises(self):
        from backend.src.app.services.single_match_value import blend_with_market

        with self.assertRaises(ValueError):
            blend_with_market(0.8, 0.6, model_weight=1.5)


class SingleMatchValueTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        override_settings(make_test_settings(rate_limit_enabled=False))

        self.client = make_api_client(app, self.Session)

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_void_odds_and_expected_roi_formula(self):
        self.assertAlmostEqual(calculate_void_odds(0.833333), 1.2, places=4)
        self.assertAlmostEqual(calculate_expected_roi(1.25, 0.833333), 0.04166625)

    def test_match_min_edge_from_bookmaker_margin(self):
        # 1/1.90 + 1/2.10 - 1 ≈ 0.0025 → clamped to floor 1.0
        self.assertEqual(calculate_match_min_edge_percent(1.90, 2.10), 1.0)
        # Wider overround ~5.26%
        self.assertAlmostEqual(calculate_match_min_edge_percent(1.80, 2.00), 5.56, places=2)
        # Few bookmakers add penalty
        self.assertAlmostEqual(
            calculate_match_min_edge_percent(1.80, 2.00, bookmaker_count=1),
            6.06,
            places=2,
        )

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
        # EV/PLAY sulla probabilita' ridotta verso il mercato (peso modello 0.5):
        # fair no-vig 0.6482 -> p_adj = 0.5*0.72 + 0.5*0.6482 = 0.6841.
        self.assertAlmostEqual(item["model_probability"], 0.72, places=4)
        self.assertAlmostEqual(item["void_odds"], 1.4618, places=4)
        self.assertAlmostEqual(item["expected_roi"], 0.0398, places=3)
        self.assertIn("suggested_min_edge_percent", item)
        self.assertIn("min_edge_percent", item)
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

    def test_route_filters_by_event_type(self):
        today = date.today()
        odds = {
            "Home/Away": {
                "Home": {"Book A": "1.52"},
                "Away": {"Book A": "2.80"},
            }
        }
        with self.Session() as session:
            session.add_all(
                [
                    NextFixture(
                        event_key=100,
                        event_date=today,
                        event_first_player="Sinner",
                        event_second_player="Alcaraz",
                        event_type_type="Atp Singles",
                        odds={"100": odds},
                        is_completed=False,
                    ),
                    NextFixture(
                        event_key=101,
                        event_date=today,
                        event_first_player="Swiatek",
                        event_second_player="Sabalenka",
                        event_type_type="Wta Singles",
                        odds={"101": odds},
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
                    MatchPrediction(
                        event_key=101,
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
                "event_type": "wta",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["match_id"], 101)


if __name__ == "__main__":
    unittest.main()
