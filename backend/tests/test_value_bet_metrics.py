import unittest

import pandas as pd

from backend.src.app.ml.model_versioning import DATASET_VERSIONS, MODEL_VERSIONS
from backend.src.app.ml.training.train_baseline import (
    ALLOWED_FEATURE_COLUMNS_V2,
    selected_feature_columns,
)
from backend.src.app.ml.training.value_bet_metrics import compute_value_bet_metrics


class ValueBetMetricsTest(unittest.TestCase):
    def test_value_bet_roi_and_hit_rate_on_synthetic_dataframe(self):
        test_df = pd.DataFrame(
            [
                {
                    "target_player_1_win": 1,
                    "market_prob_player_1": 0.45,
                    "avg_player_1_odds": 2.2,
                },
                {
                    "target_player_1_win": 0,
                    "market_prob_player_1": 0.40,
                    "avg_player_1_odds": 2.5,
                },
                {
                    "target_player_1_win": 1,
                    "market_prob_player_1": 0.55,
                    "avg_player_1_odds": 1.9,
                },
            ]
        )
        model_probs = [0.50, 0.48, 0.56]

        metrics = compute_value_bet_metrics(test_df, model_probs, edge_threshold=0.03)

        self.assertEqual(metrics["bets_count"], 2)
        self.assertAlmostEqual(metrics["hit_rate"], 0.5)
        self.assertAlmostEqual(metrics["total_profit"], 0.2)
        self.assertAlmostEqual(metrics["roi"], 0.1)
        self.assertEqual(metrics["odds_coverage_rows"], 3)

    def test_versioned_output_paths_keep_v1_and_add_v2(self):
        self.assertEqual(DATASET_VERSIONS["v1"].base_dataset, "tennis_winner_dataset.csv")
        self.assertEqual(DATASET_VERSIONS["v2"].base_dataset, "tennis_winner_dataset_v2.csv")
        self.assertEqual(MODEL_VERSIONS["v1"].metrics_filename, "baseline_metrics.json")
        self.assertEqual(MODEL_VERSIONS["v2"].metrics_filename, "baseline_v2_metrics.json")
        self.assertEqual(str(MODEL_VERSIONS["v2"].models_dir).replace("\\", "/").split("/")[-1], "v2")

    def test_v2_features_include_elo_and_rank_diff(self):
        dataframe = pd.DataFrame(
            [
                {
                    "surface": "Hard",
                    "rank_diff": 3,
                    "rank_points_diff": 120,
                    "elo_diff": 25.0,
                    "surface_elo_diff": 10.0,
                    "player_1_atp_rank": 5,
                    "atp_rank_diff": 2,
                }
            ]
        )
        features = selected_feature_columns(dataframe, model_version="v2")
        self.assertIn("elo_diff", features)
        self.assertIn("rank_points_diff", features)
        self.assertNotIn("player_1_atp_rank", features)
        self.assertEqual(set(features), set(ALLOWED_FEATURE_COLUMNS_V2[:5]))


if __name__ == "__main__":
    unittest.main()
