import unittest
from datetime import date, datetime

from backend.src.app.main import app
from backend.src.entity import Fixture, MatchPrediction, NextFixture
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client
from backend.tests.auth_helpers import clear_settings_override, make_test_settings, override_settings


class PredictionRoutesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        override_settings(make_test_settings(rate_limit_enabled=False))

        self.client = make_api_client(app, self.Session)

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_next_fixtures_predictions_route_reads_persisted_predictions(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    NextFixture(
                        event_key=100,
                        event_date=today,
                        event_first_player="A",
                        event_second_player="B",
                        tournament_name="Demo Open",
                        surface="Hard",
                        event_status="Set 2",
                        event_live="1",
                        live_score={
                            "sets": [
                                {
                                    "score_first": "6",
                                    "score_second": "4",
                                    "score_set": "1",
                                }
                            ],
                            "current_game": "30 - 15",
                            "status": "Set 2",
                        },
                        live_score_updated_at=datetime(2026, 6, 20, 14, 30, 0),
                        odds={
                            "100": {
                                "Home/Away": {
                                    "Home": {"Book A": "2.00", "Book B": "2.20"},
                                    "Away": {"Book A": "1.80", "Book B": "1.90"},
                                }
                            }
                        },
                        is_completed=False,
                    ),
                    NextFixture(
                        event_key=101,
                        event_date=today,
                        event_first_player="C",
                        event_second_player="D",
                        tournament_name="Demo Open",
                        surface="Clay",
                        is_completed=False,
                    ),
                    MatchPrediction(
                        event_key=100,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.7,
                        predicted_winner="First Player",
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/next-fixtures/predictions",
            params={"model_version": "v2", "model_name": "random_forest"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        items = payload["items"]
        self.assertEqual(payload["total"], 2)
        self.assertEqual([item["event_key"] for item in items], [100, 101])
        self.assertEqual(items[0]["prediction"]["model_name"], "random_forest")
        self.assertAlmostEqual(items[0]["prediction"]["confidence"], 0.7)
        self.assertAlmostEqual(items[0]["prediction"]["predicted_winner_odds"], 2.1)
        self.assertEqual(items[0]["prediction"]["odds_bookmaker_count"], 2)
        self.assertEqual(items[0]["event_live"], "1")
        self.assertEqual(items[0]["match_lifecycle_status"], "started")
        self.assertEqual(items[0]["live_score"]["current_game"], "30 - 15")
        self.assertEqual(items[0]["live_score"]["sets"][0]["score_first"], "6")
        self.assertIsNone(items[1]["prediction"])
        self.assertEqual(items[1]["prediction_warning"], "missing_persisted_prediction")

    def test_v3_next_fixtures_predictions_route_filters_missing_odds(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    NextFixture(
                        event_key=110,
                        event_date=today,
                        event_first_player="A",
                        event_second_player="B",
                        odds={
                            "110": {
                                "Home/Away": {
                                    "Home": {"Book A": "2.00"},
                                    "Away": {"Book A": "1.80"},
                                }
                            }
                        },
                        is_completed=False,
                    ),
                    NextFixture(
                        event_key=111,
                        event_date=today,
                        event_first_player="C",
                        event_second_player="D",
                        is_completed=False,
                    ),
                    MatchPrediction(
                        event_key=110,
                        model_version="v3",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.7,
                        predicted_winner="First Player",
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/next-fixtures/predictions",
            params={"model_version": "v3", "model_name": "random_forest"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([item["event_key"] for item in payload["items"]], [110])

    def test_next_fixtures_predictions_route_can_return_played_predictions(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    Fixture(
                        id_fixture=200,
                        event_key=200,
                        event_date=today,
                        event_first_player="A",
                        event_second_player="B",
                        event_winner="Second Player",
                        event_status="Finished",
                        event_final_result="0 - 2",
                        event_game_result="",
                        event_live="0",
                        scores=[
                            {"score_first": "4", "score_second": "6", "score_set": "1"},
                            {"score_first": "3", "score_second": "6", "score_set": "2"},
                        ],
                        odds={
                            "200": {
                                "Home/Away": {
                                    "Home": {"Book A": "2.50"},
                                    "Away": {"Book A": "1.60"},
                                }
                            }
                        },
                    ),
                    MatchPrediction(
                        event_key=200,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.4,
                        predicted_winner="Second Player",
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/next-fixtures/predictions",
            params={
                "model_version": "v2",
                "model_name": "random_forest",
                "status": "played",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        items = payload["items"]
        self.assertEqual([item["event_key"] for item in items], [200])
        self.assertTrue(items[0]["is_completed"])
        self.assertEqual(items[0]["event_winner"], "Second Player")
        self.assertEqual(items[0]["live_score"]["final_result"], "0 - 2")
        self.assertEqual(len(items[0]["live_score"]["sets"]), 2)
        self.assertAlmostEqual(items[0]["prediction"]["predicted_winner_odds"], 1.6)
        self.assertTrue(items[0]["prediction"]["is_correct"])

    def test_played_tab_excludes_fixtures_without_resolved_winner(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    Fixture(
                        id_fixture=300,
                        event_key=300,
                        event_date=today,
                        event_first_player="A",
                        event_second_player="B",
                    ),
                    Fixture(
                        id_fixture=301,
                        event_key=301,
                        event_date=today,
                        event_first_player="C",
                        event_second_player="D",
                        event_winner="First Player",
                    ),
                    MatchPrediction(
                        event_key=300,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.6,
                        predicted_winner="First Player",
                    ),
                    MatchPrediction(
                        event_key=301,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.6,
                        predicted_winner="First Player",
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/next-fixtures/predictions",
            params={
                "model_version": "v2",
                "model_name": "random_forest",
                "status": "played",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([item["event_key"] for item in payload["items"]], [301])

    def test_played_tab_includes_fixture_without_prediction(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    Fixture(
                        id_fixture=302,
                        event_key=302,
                        event_date=today,
                        event_first_player="Sinner J.",
                        event_second_player="Alcaraz C.",
                        event_winner="First Player",
                        tournament_name="Wimbledon",
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/next-fixtures/predictions",
            params={
                "model_version": "v2",
                "model_name": "random_forest",
                "status": "played",
                "player": "Sinner",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        item = payload["items"][0]
        self.assertEqual(item["event_key"], 302)
        self.assertIsNone(item["prediction"])
        self.assertEqual(item["prediction_warning"], "missing_persisted_prediction")

    def test_next_fixtures_predictions_supports_pagination(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    NextFixture(
                        event_key=index,
                        event_date=today,
                        is_completed=False,
                    )
                    for index in range(1, 6)
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/next-fixtures/predictions",
            params={"model_version": "v2", "status": "upcoming", "limit": 2, "offset": 2},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 5)
        self.assertEqual(payload["offset"], 2)
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual([item["event_key"] for item in payload["items"]], [3, 4])

    def test_played_tab_uses_fallback_model_when_best_model_missing(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    Fixture(
                        id_fixture=400,
                        event_key=400,
                        event_date=today,
                        event_first_player="A",
                        event_second_player="B",
                        event_winner="First Player",
                    ),
                    MatchPrediction(
                        event_key=400,
                        model_version="v2",
                        model_name="logistic_regression",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.6,
                        predicted_winner="First Player",
                    ),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/next-fixtures/predictions",
            params={"model_version": "v2", "status": "played"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["prediction"]["model_name"], "logistic_regression")

    def test_played_tab_outcome_filter(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    Fixture(
                        id_fixture=501,
                        event_key=501,
                        event_date=today,
                        event_winner="First Player",
                    ),
                    Fixture(
                        id_fixture=502,
                        event_key=502,
                        event_date=today,
                        event_winner="Second Player",
                    ),
                    MatchPrediction(
                        event_key=501,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.6,
                        predicted_winner="First Player",
                    ),
                    MatchPrediction(
                        event_key=502,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.4,
                        predicted_winner="First Player",
                    ),
                ]
            )
            session.commit()

        won = self.client.get(
            "/api/next-fixtures/predictions",
            params={"model_version": "v2", "status": "played", "outcome": "won"},
        )
        lost = self.client.get(
            "/api/next-fixtures/predictions",
            params={"model_version": "v2", "status": "played", "outcome": "lost"},
        )

        self.assertEqual(won.json()["total"], 1)
        self.assertEqual(won.json()["items"][0]["event_key"], 501)
        self.assertEqual(lost.json()["total"], 1)
        self.assertEqual(lost.json()["items"][0]["event_key"], 502)


if __name__ == "__main__":
    unittest.main()
