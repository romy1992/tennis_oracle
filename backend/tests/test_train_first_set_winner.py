import unittest
from datetime import date

import pandas as pd

from backend.src.app.ml.training.train_first_set_winner import (
    FIRST_SET_BENCHMARK_NAMES,
    FIRST_SET_MODEL_NAMES,
    _coin_flip_probabilities,
    _first_set_benchmark_probabilities,
    _simple_classification_metrics,
    evaluate_fold_models_first_set,
)
from backend.src.app.ml.training.walk_forward import WalkForwardConfig, WalkForwardFoldSpec


class CoinFlipProbabilitiesTest(unittest.TestCase):
    def test_always_returns_half(self):
        frame = pd.DataFrame({"x": [1, 2, 3]})
        probs = _coin_flip_probabilities(frame)

        self.assertTrue((probs == 0.5).all())
        self.assertEqual(len(probs), 3)


class SimpleClassificationMetricsTest(unittest.TestCase):
    def test_none_probabilities_returns_none(self):
        y = pd.Series([1, 0, 1])
        self.assertIsNone(_simple_classification_metrics(y, None))

    def test_single_class_returns_none(self):
        y = pd.Series([1, 1, 1])
        probs = pd.Series([0.6, 0.7, 0.8])
        self.assertIsNone(_simple_classification_metrics(y, probs))

    def test_perfect_predictions_metrics(self):
        y = pd.Series([1, 0, 1, 0])
        probs = pd.Series([0.9, 0.1, 0.9, 0.1])

        metrics = _simple_classification_metrics(y, probs)

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["accuracy"], 1.0)
        self.assertEqual(metrics["roc_auc"], 1.0)
        self.assertEqual(metrics["eval_rows"], 4)
        self.assertEqual(metrics["eval_rows_total"], 4)

    def test_nan_probabilities_excluded_from_eval_rows(self):
        y = pd.Series([1, 0, 1, 0])
        probs = pd.Series([0.9, float("nan"), 0.8, 0.2])

        metrics = _simple_classification_metrics(y, probs)

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["eval_rows"], 3)
        self.assertEqual(metrics["eval_rows_total"], 4)

    def test_all_nan_returns_none(self):
        y = pd.Series([1, 0])
        probs = pd.Series([float("nan"), float("nan")])
        self.assertIsNone(_simple_classification_metrics(y, probs))


class FirstSetBenchmarkProbabilitiesTest(unittest.TestCase):
    def test_returns_all_expected_benchmark_keys(self):
        frame = pd.DataFrame(
            {
                "avg_player_1_odds": [1.5, 2.0],
                "avg_player_2_odds": [2.5, 1.8],
                "elo_diff": [50.0, -30.0],
                "player_1_atp_rank": [10, 50],
                "player_2_atp_rank": [20, 5],
            }
        )
        benchmarks = _first_set_benchmark_probabilities(frame)

        self.assertEqual(set(benchmarks.keys()), set(FIRST_SET_BENCHMARK_NAMES))
        self.assertTrue((benchmarks["coin_flip"] == 0.5).all())


class EvaluateFoldModelsFirstSetTest(unittest.TestCase):
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
        # Target correlato a elo_diff, cosi' i modelli hanno segnale reale da imparare.
        prob = 1.0 / (1.0 + np.exp(-elo_diff / 200.0))
        target = (rng.uniform(size=n) < prob).astype(int)
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
                "target_first_set_winner": target,
            }
        )

    def test_skips_all_contenders_when_insufficient_rows(self):
        train = self._make_frame(5, seed=1)
        test = self._make_frame(3, seed=2)
        config = WalkForwardConfig(min_train_rows=50, min_test_rows=20)

        outcomes = evaluate_fold_models_first_set(
            train, test, dataset_path="dummy.csv", fold=self._fold(), config=config,
        )

        expected_names = {*FIRST_SET_MODEL_NAMES, *FIRST_SET_BENCHMARK_NAMES}
        self.assertEqual({o.model_name for o in outcomes}, expected_names)
        self.assertTrue(all(o.status == "skipped_insufficient_data" for o in outcomes))

    def test_completes_with_enough_signal(self):
        train = self._make_frame(300, seed=10)
        test = self._make_frame(100, seed=20)
        config = WalkForwardConfig(min_train_rows=50, min_test_rows=20)

        outcomes = evaluate_fold_models_first_set(
            train, test, dataset_path="dummy.csv", fold=self._fold(), config=config,
        )

        by_name = {o.model_name: o for o in outcomes}
        for model_name in FIRST_SET_MODEL_NAMES:
            self.assertEqual(by_name[model_name].status, "completed")
            self.assertIsNotNone(by_name[model_name].metrics)
            self.assertIn("roc_auc", by_name[model_name].metrics)
        # coin_flip deve sempre poter essere valutato (mai NaN) quando ci sono
        # abbastanza righe e due classi nel target.
        self.assertEqual(by_name["coin_flip"].status, "completed")
        self.assertAlmostEqual(by_name["coin_flip"].metrics["roc_auc"], 0.5, places=6)


if __name__ == "__main__":
    unittest.main()

