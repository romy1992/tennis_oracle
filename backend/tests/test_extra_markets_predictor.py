import unittest
from datetime import date
from unittest.mock import patch

from backend.src.app.ml.datasets.dataset_builder import LegacyMatchRow
from backend.src.app.ml.prediction.extra_markets_predictor import (
    predict_first_set_winner,
    predict_over_under_games,
)
from backend.src.app.ml.prediction.predictor import PreMatchFeatureBuilder
from backend.src.entity.next_fixture import NextFixture


def _fake_pipeline(prob_class_1: float):
    return type("Pipeline", (), {"predict_proba": lambda _self, _x: [[1.0 - prob_class_1, prob_class_1]]})()


class ExtraMarketsPredictorTest(unittest.TestCase):
    def _builder_with_history(self) -> PreMatchFeatureBuilder:
        builder = PreMatchFeatureBuilder()
        matches = [
            LegacyMatchRow(
                match_id=1, match_date=date(2026, 6, 1), surface="Hard",
                player_1_id=10, player_2_id=20, target_player_1_win=1,
            ),
            LegacyMatchRow(
                match_id=2, match_date=date(2026, 6, 10), surface="Hard",
                player_1_id=10, player_2_id=30, target_player_1_win=0,
            ),
        ]
        builder._ingest_history(matches)
        return builder

    def _fixture(self, odds: dict | None) -> NextFixture:
        return NextFixture(
            event_key=100,
            event_date=date(2026, 6, 21),
            surface="Hard",
            first_player_key=10,
            second_player_key=20,
            event_first_player="A",
            event_second_player="B",
            odds=odds,
        )

    def _match_winner_odds(self) -> dict:
        return {
            "100": {
                "Home/Away": {
                    "Home": {"Book A": "2.00", "Book B": "2.20"},
                    "Away": {"Book A": "1.80", "Book B": "1.90"},
                }
            }
        }

    def _match_winner_and_first_set_odds(self) -> dict:
        payload = self._match_winner_odds()["100"]
        payload["Home/Away (1st Set)"] = {
            "Home": {"Book A": "1.70", "Book B": "1.80"},
            "Away": {"Book A": "2.10", "Book B": "2.00"},
        }
        return {"100": payload}

    def _match_winner_and_ou_odds(self) -> dict:
        payload = self._match_winner_odds()["100"]
        payload["Over/Under by Games in Match"] = {
            "Over/Under by Games in Match Over": {"20.5": {"Betfair": "1.85"}},
            "Over/Under by Games in Match Under": {"20.5": {"Betfair": "1.95"}},
        }
        return {"100": payload}

    # --- First Set Winner ---

    def test_missing_player_keys_returns_none_probability(self):
        builder = self._builder_with_history()
        fixture = NextFixture(event_key=999, event_date=date(2026, 6, 21))
        result = predict_first_set_winner(fixture, feature_builder=builder)
        self.assertIsNone(result["probability"])
        self.assertIn("missing_player_keys_or_date", result["warnings"])

    def test_missing_odds_returns_none_probability(self):
        builder = self._builder_with_history()
        fixture = self._fixture(odds=None)
        result = predict_first_set_winner(fixture, feature_builder=builder)
        self.assertIsNone(result["probability"])
        self.assertIn("missing_odds", result["warnings"])

    def test_missing_first_set_odds_returns_none_probability(self):
        builder = self._builder_with_history()
        fixture = self._fixture(odds=self._match_winner_odds())
        result = predict_first_set_winner(fixture, feature_builder=builder)
        self.assertIsNone(result["probability"])
        self.assertIn("missing_first_set_odds", result["warnings"])

    @patch("backend.src.app.ml.prediction.extra_markets_predictor._load_extra_model_artifact")
    def test_predicts_first_player_favorite(self, mock_load_model):
        mock_load_model.return_value = {
            "feature_columns": ["surface", "rank_diff", "h2h_player_1_wins"],
            "pipeline": _fake_pipeline(0.65),
        }
        builder = self._builder_with_history()
        fixture = self._fixture(odds=self._match_winner_and_first_set_odds())

        result = predict_first_set_winner(fixture, feature_builder=builder)

        self.assertEqual(result["market"], "first_set_winner")
        self.assertEqual(result["model_version"], "first_set_winner_v2")
        self.assertEqual(result["model_name"], "logistic_regression")
        self.assertAlmostEqual(result["prob_player_1"], 0.65)
        self.assertAlmostEqual(result["probability"], 0.65)
        self.assertEqual(result["selection"], "First Player")
        self.assertAlmostEqual(result["market_odds"], 1.75)

    @patch("backend.src.app.ml.prediction.extra_markets_predictor._load_extra_model_artifact")
    def test_predicts_second_player_favorite_probability_is_flipped(self, mock_load_model):
        mock_load_model.return_value = {
            "feature_columns": ["surface", "rank_diff", "h2h_player_1_wins"],
            "pipeline": _fake_pipeline(0.3),
        }
        builder = self._builder_with_history()
        fixture = self._fixture(odds=self._match_winner_and_first_set_odds())

        result = predict_first_set_winner(fixture, feature_builder=builder)

        self.assertEqual(result["selection"], "Second Player")
        self.assertAlmostEqual(result["prob_player_1"], 0.3)
        # probability e' sempre riferita alla selection scelta (>= 0.5)
        self.assertAlmostEqual(result["probability"], 0.7)
        self.assertAlmostEqual(result["market_odds"], 2.05)

    @patch("backend.src.app.ml.prediction.extra_markets_predictor._load_extra_model_artifact")
    def test_model_not_found_is_reported_as_warning(self, mock_load_model):
        mock_load_model.side_effect = FileNotFoundError("model missing")
        builder = self._builder_with_history()
        fixture = self._fixture(odds=self._match_winner_and_first_set_odds())

        result = predict_first_set_winner(fixture, feature_builder=builder)

        self.assertIsNone(result["probability"])
        self.assertTrue(any("model missing" in w for w in result["warnings"]))

    # --- Over/Under Games ---

    def test_over_under_missing_ou_odds_returns_none(self):
        builder = self._builder_with_history()
        fixture = self._fixture(odds=self._match_winner_odds())  # no O/U market
        result = predict_over_under_games(fixture, feature_builder=builder)
        self.assertIsNone(result["probability"])
        self.assertIn("missing_over_under_odds", result["warnings"])

    @patch("backend.src.app.ml.prediction.extra_markets_predictor._load_extra_model_artifact")
    def test_over_under_predicts_over(self, mock_load_model):
        mock_load_model.return_value = {
            "feature_columns": ["surface", "avg_over_odds", "avg_under_odds"],
            "pipeline": _fake_pipeline(0.58),
        }
        builder = self._builder_with_history()
        fixture = self._fixture(odds=self._match_winner_and_ou_odds())

        result = predict_over_under_games(fixture, feature_builder=builder)

        self.assertEqual(result["market"], "over_under_games")
        self.assertEqual(result["model_version"], "over_under_games_v1")
        self.assertEqual(result["line"], 20.5)
        self.assertEqual(result["selection"], "Over 20.5")
        self.assertAlmostEqual(result["prob_over"], 0.58)
        self.assertAlmostEqual(result["probability"], 0.58)

    @patch("backend.src.app.ml.prediction.extra_markets_predictor._load_extra_model_artifact")
    def test_over_under_predicts_under(self, mock_load_model):
        mock_load_model.return_value = {
            "feature_columns": ["surface", "avg_over_odds", "avg_under_odds"],
            "pipeline": _fake_pipeline(0.35),
        }
        builder = self._builder_with_history()
        fixture = self._fixture(odds=self._match_winner_and_ou_odds())

        result = predict_over_under_games(fixture, feature_builder=builder)

        self.assertEqual(result["selection"], "Under 20.5")
        self.assertAlmostEqual(result["probability"], 0.65)


if __name__ == "__main__":
    unittest.main()

