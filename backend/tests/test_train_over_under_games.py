import unittest
from datetime import date

import pandas as pd

from backend.src.app.ml.training.train_over_under_games import (
    OVER_UNDER_BENCHMARK_NAMES,
    OVER_UNDER_MODEL_NAMES,
    _classification_and_roi_metrics,
    _coin_flip_probabilities,
    _market_favorite_over_under_probabilities,
    _market_no_vig_over_under_probabilities,
    _over_under_benchmark_probabilities,
    evaluate_fold_models_over_under_games,
)
from backend.src.app.ml.training.walk_forward import WalkForwardConfig, WalkForwardFoldSpec


class CoinFlipProbabilitiesTest(unittest.TestCase):
    def test_always_returns_half(self):
        frame = pd.DataFrame({"x": [1, 2, 3]})
        probs = _coin_flip_probabilities(frame)
        self.assertTrue((probs == 0.5).all())
        self.assertEqual(len(probs), 3)


class MarketFavoriteOverUnderTest(unittest.TestCase):
    def test_lower_over_odds_means_over_favorite(self):
        frame = pd.DataFrame({"avg_over_odds": [1.5, 2.5], "avg_under_odds": [2.5, 1.5]})
        probs = _market_favorite_over_under_probabilities(frame)
        self.assertEqual(list(probs), [1.0, 0.0])

    def test_tie_returns_half(self):
        frame = pd.DataFrame({"avg_over_odds": [2.0], "avg_under_odds": [2.0]})
        probs = _market_favorite_over_under_probabilities(frame)
        self.assertEqual(list(probs), [0.5])

    def test_missing_odds_returns_nan(self):
        frame = pd.DataFrame({"avg_over_odds": [None], "avg_under_odds": [None]})
        probs = _market_favorite_over_under_probabilities(frame)
        self.assertTrue(probs.isna().all())


class MarketNoVigOverUnderTest(unittest.TestCase):
    def test_probabilities_sum_to_one(self):
        frame = pd.DataFrame({"avg_over_odds": [1.9], "avg_under_odds": [1.9]})
        probs = _market_no_vig_over_under_probabilities(frame)
        self.assertAlmostEqual(float(probs.iloc[0]), 0.5, places=6)

    def test_asymmetric_odds_produce_asymmetric_probability(self):
        frame = pd.DataFrame({"avg_over_odds": [1.5], "avg_under_odds": [2.5]})
        probs = _market_no_vig_over_under_probabilities(frame)
        self.assertGreater(float(probs.iloc[0]), 0.5)


class OverUnderBenchmarkProbabilitiesTest(unittest.TestCase):
    def test_returns_all_expected_benchmark_keys(self):
        frame = pd.DataFrame({"avg_over_odds": [1.8, 2.1], "avg_under_odds": [2.0, 1.75]})
        benchmarks = _over_under_benchmark_probabilities(frame)
        self.assertEqual(set(benchmarks.keys()), set(OVER_UNDER_BENCHMARK_NAMES))


class ClassificationAndRoiMetricsTest(unittest.TestCase):
    def test_none_probabilities_returns_none(self):
        y = pd.Series([1, 0, 1])
        test = pd.DataFrame({"x": [1, 2, 3]})
        self.assertIsNone(_classification_and_roi_metrics(y, None, test))

    def test_single_class_returns_none(self):
        y = pd.Series([1, 1, 1])
        probs = pd.Series([0.6, 0.7, 0.8])
        test = pd.DataFrame({"x": [1, 2, 3]})
        self.assertIsNone(_classification_and_roi_metrics(y, probs, test))

    def test_perfect_predictions_include_value_bet_when_odds_present(self):
        y = pd.Series([1, 0, 1, 0])
        probs = pd.Series([0.9, 0.1, 0.9, 0.1])
        test = pd.DataFrame(
            {
                "avg_over_odds": [1.8, 1.9, 1.85, 1.95],
                "avg_under_odds": [2.0, 1.8, 2.1, 1.85],
            }
        )

        metrics = _classification_and_roi_metrics(y, probs, test)

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["accuracy"], 1.0)
        self.assertIsNotNone(metrics["value_bet"])
        self.assertEqual(metrics["value_bet"]["bets_settled"], 4)

    def test_missing_odds_columns_yields_none_value_bet(self):
        y = pd.Series([1, 0, 1, 0])
        probs = pd.Series([0.9, 0.1, 0.9, 0.1])
        test = pd.DataFrame({"x": [1, 2, 3, 4]})

        metrics = _classification_and_roi_metrics(y, probs, test)

        self.assertIsNotNone(metrics)
        self.assertIsNone(metrics["value_bet"])


class EvaluateFoldModelsOverUnderGamesTest(unittest.TestCase):
    def _fold(self) -> WalkForwardFoldSpec:
        return WalkForwardFoldSpec(
            fold_index=0,
            train_start=date(2024, 1, 1),
            train_end=date(2024, 6, 30),
            test_start=date(2024, 7, 1),
            test_end=date(2024, 9, 30),
            mode="expanding",
        )

    def _make_frame(self, n: int, *, seed: int) -> pd.DataFrame:
        import numpy as np

        rng = np.random.RandomState(seed)
        elo_diff = rng.normal(0, 100, size=n)
        over_odds = rng.uniform(1.6, 2.2, size=n)
        under_odds = rng.uniform(1.6, 2.2, size=n)
        prob_over = 1.0 / over_odds / ((1.0 / over_odds) + (1.0 / under_odds))
        target = (rng.uniform(size=n) < prob_over).astype(int)
        return pd.DataFrame(
            {
                "match_id": range(n),
                "match_date": [date(2024, 1, 1)] * n,
                "surface": ["Hard"] * n,
                "elo_diff": elo_diff,
                "player_1_elo": 1500 + elo_diff / 2,
                "player_2_elo": 1500 - elo_diff / 2,
                "player_1_atp_rank": rng.randint(1, 200, size=n),
                "player_2_atp_rank": rng.randint(1, 200, size=n),
                "rank_diff": rng.normal(0, 50, size=n),
                "avg_player_1_odds": rng.uniform(1.2, 4.0, size=n),
                "avg_player_2_odds": rng.uniform(1.2, 4.0, size=n),
                "avg_market_prob_player_1": rng.uniform(0.2, 0.8, size=n),
                "avg_market_prob_player_2": rng.uniform(0.2, 0.8, size=n),
                "avg_bookmaker_margin": rng.uniform(0.0, 0.1, size=n),
                "odds_bookmaker_count": rng.randint(1, 10, size=n),
                "avg_over_odds": over_odds,
                "avg_under_odds": under_odds,
                "avg_market_prob_over": prob_over,
                "avg_market_prob_under": 1.0 - prob_over,
                "avg_bookmaker_margin_ou_games": rng.uniform(0.0, 0.1, size=n),
                "odds_bookmaker_count_ou_games": rng.randint(1, 10, size=n),
                "target_over_under_games": target,
            }
        )

    def test_skips_all_contenders_when_insufficient_rows(self):
        train = self._make_frame(5, seed=1)
        test = self._make_frame(3, seed=2)
        config = WalkForwardConfig(min_train_rows=50, min_test_rows=20)

        outcomes = evaluate_fold_models_over_under_games(
            train, test, dataset_path="dummy.csv", fold=self._fold(), config=config,
        )

        expected_names = {*OVER_UNDER_MODEL_NAMES, *OVER_UNDER_BENCHMARK_NAMES}
        self.assertEqual({o.model_name for o in outcomes}, expected_names)
        self.assertTrue(all(o.status == "skipped_insufficient_data" for o in outcomes))

    def test_completes_with_enough_signal(self):
        train = self._make_frame(300, seed=10)
        test = self._make_frame(100, seed=20)
        config = WalkForwardConfig(min_train_rows=50, min_test_rows=20)

        outcomes = evaluate_fold_models_over_under_games(
            train, test, dataset_path="dummy.csv", fold=self._fold(), config=config,
        )

        by_name = {o.model_name: o for o in outcomes}
        for model_name in OVER_UNDER_MODEL_NAMES:
            self.assertEqual(by_name[model_name].status, "completed")
            self.assertIsNotNone(by_name[model_name].metrics)
            self.assertIn("roc_auc", by_name[model_name].metrics)
            self.assertIsNotNone(by_name[model_name].metrics.get("value_bet"))
        self.assertEqual(by_name["coin_flip"].status, "completed")
        self.assertAlmostEqual(by_name["coin_flip"].metrics["roc_auc"], 0.5, places=6)
        self.assertEqual(by_name["market_no_vig"].status, "completed")


if __name__ == "__main__":
    unittest.main()

