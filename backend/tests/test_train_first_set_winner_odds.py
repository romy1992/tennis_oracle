import unittest
from datetime import date

import pandas as pd

from backend.src.app.ml.training.train_first_set_winner_odds import (
    FIRST_SET_ODDS_BENCHMARK_NAMES,
    FIRST_SET_ODDS_MODEL_NAMES,
    _classification_and_roi_metrics,
    _coin_flip_probabilities,
    _first_set_odds_benchmark_probabilities,
    _market_favorite_first_set_probabilities,
    _market_no_vig_first_set_probabilities,
    evaluate_fold_models_first_set_odds,
)
from backend.src.app.ml.training.walk_forward import WalkForwardConfig, WalkForwardFoldSpec


class FirstSetOddsBenchmarkTest(unittest.TestCase):
    def test_favorite_uses_lower_first_set_odds(self):
        frame = pd.DataFrame(
            {"avg_first_set_player_1_odds": [1.5, 2.5], "avg_first_set_player_2_odds": [2.5, 1.5]}
        )
        self.assertEqual(list(_market_favorite_first_set_probabilities(frame)), [1.0, 0.0])

    def test_no_vig_symmetric(self):
        frame = pd.DataFrame(
            {"avg_first_set_player_1_odds": [1.9], "avg_first_set_player_2_odds": [1.9]}
        )
        self.assertAlmostEqual(float(_market_no_vig_first_set_probabilities(frame).iloc[0]), 0.5)

    def test_benchmark_keys(self):
        frame = pd.DataFrame(
            {
                "avg_first_set_player_1_odds": [1.8],
                "avg_first_set_player_2_odds": [2.0],
                "avg_player_1_odds": [1.6],
                "avg_player_2_odds": [2.3],
            }
        )
        self.assertEqual(set(_first_set_odds_benchmark_probabilities(frame)), set(FIRST_SET_ODDS_BENCHMARK_NAMES))
        self.assertTrue((_coin_flip_probabilities(frame) == 0.5).all())


class FirstSetOddsMetricsTest(unittest.TestCase):
    def test_value_bet_uses_first_set_odds(self):
        y = pd.Series([1, 0, 1, 0])
        probs = pd.Series([0.9, 0.1, 0.9, 0.1])
        test = pd.DataFrame(
            {
                "avg_first_set_player_1_odds": [1.8, 1.9, 1.85, 1.95],
                "avg_first_set_player_2_odds": [2.0, 1.8, 2.1, 1.85],
            }
        )
        metrics = _classification_and_roi_metrics(y, probs, test)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["accuracy"], 1.0)
        self.assertEqual(metrics["value_bet"]["bets_settled"], 4)

    def test_missing_odds_columns_yield_none_value_bet(self):
        metrics = _classification_and_roi_metrics(
            pd.Series([1, 0, 1, 0]),
            pd.Series([0.9, 0.1, 0.9, 0.1]),
            pd.DataFrame({"x": [1, 2, 3, 4]}),
        )
        self.assertIsNotNone(metrics)
        self.assertIsNone(metrics["value_bet"])


class EvaluateFoldFirstSetOddsTest(unittest.TestCase):
    def test_skips_when_insufficient_rows(self):
        frame = pd.DataFrame(
            {
                "match_date": [date(2024, 1, 1)] * 5,
                "surface": ["Hard"] * 5,
                "elo_diff": [10.0] * 5,
                "avg_first_set_player_1_odds": [1.8] * 5,
                "avg_first_set_player_2_odds": [2.0] * 5,
                "target_first_set_winner": [1, 0, 1, 0, 1],
            }
        )
        fold = WalkForwardFoldSpec(
            fold_index=0,
            train_start=date(2024, 1, 1),
            train_end=date(2024, 6, 30),
            test_start=date(2024, 7, 1),
            test_end=date(2024, 9, 30),
            mode="expanding",
        )
        outcomes = evaluate_fold_models_first_set_odds(
            frame,
            frame.iloc[:3],
            dataset_path="dummy.csv",
            fold=fold,
            config=WalkForwardConfig(min_train_rows=50, min_test_rows=20),
        )
        expected = {*FIRST_SET_ODDS_MODEL_NAMES, *FIRST_SET_ODDS_BENCHMARK_NAMES}
        self.assertEqual({item.model_name for item in outcomes}, expected)
        self.assertTrue(all(item.status == "skipped_insufficient_data" for item in outcomes))
