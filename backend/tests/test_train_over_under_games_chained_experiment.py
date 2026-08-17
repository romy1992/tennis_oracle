import unittest
from datetime import date

import numpy as np
import pandas as pd

from backend.src.app.ml.training.train_over_under_games_chained_experiment import (
    CHAINED_FEATURE_COLUMN,
    add_chained_match_winner_feature,
    run_over_under_games_chained_experiment,
)
from backend.src.app.ml.training.walk_forward import WalkForwardConfig


def _make_frame(n: int, *, seed: int) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    elo_diff = rng.normal(0, 100, size=n)
    prob_match_winner = 1.0 / (1.0 + np.exp(-elo_diff / 200.0))
    match_winner_target = (rng.uniform(size=n) < prob_match_winner).astype(int)

    over_odds = rng.uniform(1.6, 2.2, size=n)
    under_odds = rng.uniform(1.6, 2.2, size=n)
    prob_over = 1.0 / over_odds / ((1.0 / over_odds) + (1.0 / under_odds))
    ou_target = (rng.uniform(size=n) < prob_over).astype(int)

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
            "target_player_1_win": match_winner_target,
            "target_over_under_games": ou_target,
        }
    )


class AddChainedMatchWinnerFeatureTest(unittest.TestCase):
    def test_adds_probability_column_with_enough_signal(self):
        train = _make_frame(200, seed=1)
        test = _make_frame(50, seed=2)

        train_out, test_out, trained = add_chained_match_winner_feature(train, test, random_state=42)

        self.assertTrue(trained)
        self.assertIn(CHAINED_FEATURE_COLUMN, train_out.columns)
        self.assertIn(CHAINED_FEATURE_COLUMN, test_out.columns)
        self.assertTrue(train_out[CHAINED_FEATURE_COLUMN].between(0.0, 1.0).all())
        self.assertTrue(test_out[CHAINED_FEATURE_COLUMN].between(0.0, 1.0).all())

    def test_missing_target_column_returns_nan_feature(self):
        train = _make_frame(50, seed=1).drop(columns=["target_player_1_win"])
        test = _make_frame(20, seed=2).drop(columns=["target_player_1_win"])

        train_out, test_out, trained = add_chained_match_winner_feature(train, test, random_state=42)

        self.assertFalse(trained)
        self.assertTrue(train_out[CHAINED_FEATURE_COLUMN].isna().all())
        self.assertTrue(test_out[CHAINED_FEATURE_COLUMN].isna().all())

    def test_insufficient_rows_returns_nan_feature(self):
        train = _make_frame(5, seed=1)
        test = _make_frame(5, seed=2)

        _, _, trained = add_chained_match_winner_feature(train, test, random_state=42)

        self.assertFalse(trained)

    def test_single_class_target_returns_nan_feature(self):
        train = _make_frame(50, seed=1)
        train["target_player_1_win"] = 1
        test = _make_frame(20, seed=2)

        _, _, trained = add_chained_match_winner_feature(train, test, random_state=42)

        self.assertFalse(trained)


class RunOverUnderGamesChainedExperimentTest(unittest.TestCase):
    def test_runs_end_to_end_and_writes_report(self):
        import backend.src.app.ml.training.train_over_under_games_chained_experiment as module

        combined = pd.concat(
            [_make_frame(400, seed=i) for i in range(6)], ignore_index=True,
        )
        combined["match_date"] = pd.to_datetime(
            pd.Series(range(len(combined))).apply(lambda i: date(2024, 1, 1) + pd.Timedelta(days=i))
        )
        combined["match_id"] = range(len(combined))

        original_build = module.build_over_under_games_dataframe
        original_load_baseline = module._load_baseline_comparison
        try:
            module.build_over_under_games_dataframe = lambda db, line, processed_dir: (combined, "dummy.csv")
            module._load_baseline_comparison = lambda reports_dir: None

            report = run_over_under_games_chained_experiment(
                db=None,
                config=WalkForwardConfig(
                    initial_train_days=200, test_days=100, step_days=100,
                    min_train_rows=50, min_test_rows=20,
                ),
                reports_dir="backend/data/reports",
            )
        finally:
            module.build_over_under_games_dataframe = original_build
            module._load_baseline_comparison = original_load_baseline

        self.assertIn("aggregate_metrics", report)
        self.assertIn("coverage", report)
        self.assertGreaterEqual(report["coverage"]["folds_planned"], 1)
        self.assertTrue(report["results_path"].endswith("over_under_games_chained_experiment_results.json"))


if __name__ == "__main__":
    unittest.main()

