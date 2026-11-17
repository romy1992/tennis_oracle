"""Additive freshness / data-quality fields of GET /api/next-fixtures/predictions."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from backend.src.app.main import app
from backend.src.entity import MatchPrediction, NextFixture
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot
from backend.tests.auth_helpers import clear_settings_override, make_test_settings, override_settings
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client

ODDS = {
    "100": {
        "Home/Away": {
            "Home": {"Book A": "2.00", "Book B": "2.20"},
            "Away": {"Book A": "1.80", "Book B": "1.90"},
        }
    }
}


def _snapshot(event_key: int, captured_at: datetime, index: int, market: str = "match_winner") -> PrematchOddsSnapshot:
    return PrematchOddsSnapshot(
        event_key=event_key,
        market=market,
        selection="First Player",
        bookmaker="Book A",
        odds=2.0,
        implied_probability=0.5,
        margin=0.05,
        captured_at=captured_at,
        source="import",
        snapshot_type="auto",
        detection_hash=f"hash-{event_key}-{index}",
    )


class PredictionFreshnessFieldsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        override_settings(make_test_settings(rate_limit_enabled=False))
        self.client = make_api_client(app, self.Session)

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def _seed(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    NextFixture(event_key=100, event_date=today, surface="Hard", odds=ODDS, is_completed=False),
                    NextFixture(event_key=101, event_date=today, surface=None, odds=ODDS, is_completed=False),
                    MatchPrediction(
                        event_key=100,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.7,
                        predicted_winner="First Player",
                    ),
                    MatchPrediction(
                        event_key=101,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.4,
                        predicted_winner="Second Player",
                    ),
                    _snapshot(100, datetime(2026, 6, 20, 8, 0, 0), 1),
                    _snapshot(100, datetime(2026, 6, 20, 9, 30, 0), 2),
                    # A later capture of another market must not be reported as match-winner freshness.
                    _snapshot(100, datetime(2026, 6, 20, 11, 0, 0), 3, market="first_set_winner"),
                ]
            )
            session.commit()

    def _items(self):
        response = self.client.get(
            "/api/next-fixtures/predictions",
            params={"model_version": "v2", "model_name": "random_forest"},
        )
        self.assertEqual(response.status_code, 200)
        return {item["event_key"]: item for item in response.json()["items"]}

    def test_odds_captured_at_is_latest_match_winner_capture_in_utc(self):
        self._seed()
        items = self._items()
        self.assertEqual(items[100]["odds_captured_at"], "2026-06-20T09:30:00Z")

    def test_odds_captured_at_is_null_when_no_capture_is_recorded(self):
        self._seed()
        self.assertIsNone(self._items()[101]["odds_captured_at"])

    def test_data_quality_reports_what_was_and_was_not_evaluated(self):
        self._seed()
        items = self._items()
        known = items[100]["prediction"]["data_quality"]
        self.assertEqual(known["status"], "limited")  # two bookmakers only
        self.assertEqual(known["reasons"], ["few_bookmakers"])
        self.assertEqual(known["not_evaluated"], ["player_history", "ranking"])
        self.assertIsNone(known["details"]["player_1_prior_matches"])

        unknown_surface = items[101]["prediction"]["data_quality"]
        self.assertIn("surface_unknown", unknown_surface["reasons"])

    def test_existing_fields_are_unchanged(self):
        self._seed()
        prediction = self._items()[100]["prediction"]
        for field in (
            "event_key",
            "model_version",
            "model_name",
            "predicted_at",
            "prob_player_1_win",
            "predicted_winner",
            "confidence",
            "features_available",
            "warnings",
            "odds_bookmaker_count",
        ):
            self.assertIn(field, prediction)
        self.assertAlmostEqual(prediction["confidence"], 0.7)


if __name__ == "__main__":
    unittest.main()
