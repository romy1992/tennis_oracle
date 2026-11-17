"""``prediction.data_quality`` on GET /api/next-fixtures/predictions (read path).

Covers what the stored prediction cannot carry: the ATP enrichment columns the
serving pipeline never builds (always reported, no query) and the players'
match history (opt-in, one aggregate query per page).
"""

from __future__ import annotations

import unittest
import unittest.mock
from datetime import date, datetime, timedelta

from backend.src.app.main import app
from backend.src.app.ml.datasets.dataset_builder import load_legacy_match_rows
from backend.src.app.ml.prediction import predictor
from backend.src.app.ml.prediction.data_sufficiency import LOW_HISTORY_MATCHES
from backend.src.app.ml.prediction.predictor import (
    PreMatchFeatureBuilder,
    serving_unavailable_feature_columns,
)
from backend.src.app.services import predictions as service
from backend.src.entity import Fixture, MatchPrediction, NextFixture
from backend.tests.auth_helpers import clear_settings_override, make_test_settings, override_settings
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client

ENRICHMENT_COLUMNS = {
    "player_1_age",
    "player_2_age",
    "age_diff",
    "player_1_height",
    "player_2_height",
    "height_diff",
    "player_1_hand",
    "player_2_hand",
    "atp_surface",
    "atp_tourney_level",
    "atp_round",
    "atp_best_of",
    "atp_match_found",
}
ODDS = {
    "Home/Away": {
        "Home": {f"Book {i}": "2.00" for i in range(6)},
        "Away": {f"Book {i}": "1.85" for i in range(6)},
    }
}
VETERAN, REGULAR, ROOKIE, NEWCOMER = 10, 20, 30, 40


def _completed(event_key: int, first: int, second: int, **overrides) -> Fixture:
    values = dict(
        event_key=event_key,
        event_date=date.today() - timedelta(days=30 + event_key % 20),
        first_player_key=first,
        second_player_key=second,
        event_winner="First Player",
        event_final_result="2 - 0",
        event_type_type="Atp Singles",
    )
    values.update(overrides)
    return Fixture(**values)


class ServingUnavailableColumnsTest(unittest.TestCase):
    def test_v4_static_list_matches_what_the_committed_artifact_misses(self):
        static = serving_unavailable_feature_columns("v4")
        self.assertEqual(set(static), ENRICHMENT_COLUMNS)

        artifact = predictor._load_model_artifact("v4", "voting_ensemble")
        builder = PreMatchFeatureBuilder()
        row, _warnings, _available = builder.build_feature_row(
            event_key=1,
            match_date=date(2026, 6, 30),
            surface="Hard",
            player_1_id=1,
            player_2_id=2,
            model_version="v4",
            odds=ODDS,
        )
        cleaned = predictor._clean_features(row, "v4")
        missing = [column for column in artifact["feature_columns"] if column not in cleaned.columns]
        self.assertEqual(sorted(missing), sorted(static))

    def test_no_post_match_column_is_ever_reported_or_allowed(self):
        for version in ("v1", "v2", "v3", "v4"):
            self.assertFalse({"atp_minutes", "atp_score"} & set(serving_unavailable_feature_columns(version)))


class PredictionDataQualityReadTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self._use_settings()

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def _use_settings(self, **overrides):
        clear_settings_override()
        app.dependency_overrides.clear()
        settings = make_test_settings(rate_limit_enabled=False, **overrides)
        override_settings(settings)
        self.client = make_api_client(app, self.Session, settings=settings)

    def _seed(self):
        today = date.today()
        fixtures: list[Fixture] = []
        key = 1000
        for _ in range(LOW_HISTORY_MATCHES + 3):  # VETERAN: enough history, on both sides of the draw
            key += 1
            fixtures.append(_completed(key, VETERAN, REGULAR))
        for _ in range(2):  # ROOKIE: below the low-history threshold, as second player
            key += 1
            fixtures.append(_completed(key, VETERAN, ROOKIE, event_winner="Second Player"))
        # Rows the predictor does not ingest: they must not count as history.
        fixtures += [
            _completed(2001, NEWCOMER, VETERAN, event_type_type="Atp Doubles"),
            _completed(2002, NEWCOMER, VETERAN, event_winner=None),
            _completed(2003, NEWCOMER, VETERAN, event_final_result="-"),
            _completed(2004, NEWCOMER, VETERAN, event_final_result=None),
            _completed(2005, NEWCOMER, VETERAN, event_date=None),
            _completed(2006, NEWCOMER, None),
            _completed(2007, NEWCOMER, VETERAN, event_type_type="Davis Cup Teams Singles"),
        ]
        with self.Session() as session:
            session.add_all(fixtures)
            session.add_all(
                [
                    NextFixture(
                        event_key=1,
                        event_date=today,
                        surface="Hard",
                        odds=ODDS,
                        is_completed=False,
                        first_player_key=VETERAN,
                        second_player_key=REGULAR,
                    ),
                    NextFixture(
                        event_key=2,
                        event_date=today,
                        surface="Hard",
                        odds=ODDS,
                        is_completed=False,
                        first_player_key=NEWCOMER,
                        second_player_key=ROOKIE,
                    ),
                    NextFixture(
                        event_key=3,
                        event_date=today,
                        surface="Hard",
                        odds=ODDS,
                        is_completed=False,
                        first_player_key=None,
                        second_player_key=VETERAN,
                    ),
                ]
            )
            session.add_all(
                MatchPrediction(
                    event_key=event_key,
                    model_version="v4",
                    model_name="voting_ensemble",
                    predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                    prob_player_1_win=0.61,
                    predicted_winner="First Player",
                )
                for event_key in (1, 2, 3)
            )
            session.commit()

    def _items(self):
        response = self.client.get(
            "/api/next-fixtures/predictions",
            params={"model_version": "v4", "model_name": "voting_ensemble"},
        )
        self.assertEqual(response.status_code, 200)
        return {item["event_key"]: item for item in response.json()["items"]}

    def test_default_reports_enrichment_gap_and_leaves_history_not_evaluated(self):
        self._seed()
        quality = self._items()[2]["prediction"]["data_quality"]

        self.assertEqual(quality["systemic_gaps"], ["enrichment_features_unavailable"])
        self.assertEqual(set(quality["details"]["unavailable_feature_columns"]), ENRICHMENT_COLUMNS)
        self.assertIn("enrichment_features", quality["evaluated"])
        self.assertEqual(quality["not_evaluated"], ["player_history", "ranking"])
        self.assertIsNone(quality["details"]["player_1_prior_matches"])
        # A systemic gap is not a downgrade, and unknown history is not assumed.
        self.assertEqual(quality["status"], "sufficient")
        self.assertEqual(quality["reasons"], [])

    def test_default_does_not_query_the_fixture_history(self):
        self._seed()
        with unittest.mock.patch.object(service, "_prior_match_counts_by_player") as counts:
            self._items()
        counts.assert_not_called()

    def test_opt_in_history_flags_players_without_or_with_little_history(self):
        self._seed()
        self._use_settings(prediction_data_quality_history_enabled=True)
        items = self._items()

        known = items[1]["prediction"]["data_quality"]
        self.assertEqual(known["status"], "sufficient")
        self.assertEqual(known["reasons"], [])
        self.assertEqual(known["details"]["player_1_prior_matches"], LOW_HISTORY_MATCHES + 3 + 2)
        self.assertEqual(known["details"]["player_2_prior_matches"], LOW_HISTORY_MATCHES + 3)
        self.assertIn("player_history", known["evaluated"])
        self.assertEqual(known["not_evaluated"], ["ranking"])

        thin = items[2]["prediction"]["data_quality"]
        self.assertEqual(thin["status"], "limited")
        self.assertEqual(thin["reasons"], ["player_1_no_history", "player_2_low_history"])
        self.assertEqual(thin["details"]["player_1_prior_matches"], 0)
        self.assertEqual(thin["details"]["player_2_prior_matches"], 2)
        # The published numbers are untouched: the status only describes them.
        self.assertEqual(items[2]["prediction"]["prob_player_1_win"], 0.61)
        self.assertEqual(items[2]["prediction"]["predicted_winner"], "First Player")

    def test_missing_player_key_is_not_reported_as_no_history(self):
        self._seed()
        self._use_settings(prediction_data_quality_history_enabled=True)
        quality = self._items()[3]["prediction"]["data_quality"]
        self.assertIsNone(quality["details"]["player_1_prior_matches"])
        self.assertNotIn("player_1_no_history", quality["reasons"])

    def test_history_counts_match_what_the_predictor_ingests(self):
        self._seed()
        with self.Session() as session:
            counts = service._prior_match_counts_by_player(session, [VETERAN, REGULAR, ROOKIE, NEWCOMER, 999])
            builder = PreMatchFeatureBuilder()
            builder._ingest_history(load_legacy_match_rows(session))
        self.assertEqual(counts[999], 0)
        self.assertEqual(counts[NEWCOMER], 0)
        for player in (VETERAN, REGULAR, ROOKIE, NEWCOMER, 999):
            self.assertEqual(counts[player], builder.prior_match_count(player), player)

    def test_no_player_keys_means_no_query(self):
        with self.Session() as session:
            self.assertEqual(service._prior_match_counts_by_player(session, []), {})


if __name__ == "__main__":
    unittest.main()
