import unittest

import pandas as pd

from backend.src.app.ml.training.train_baseline import (
    LEAKAGE_EXCLUDED_COLUMNS,
    filter_rows_with_valid_odds,
    selected_feature_columns,
    temporal_train_test_split,
)


class TrainBaselineTest(unittest.TestCase):
    def test_temporal_split_uses_oldest_rows_for_training(self):
        dataframe = pd.DataFrame(
            [
                {"match_date": "2024-01-03", "target_player_1_win": 1, "rank_diff": 3},
                {"match_date": "2024-01-01", "target_player_1_win": 0, "rank_diff": 1},
                {"match_date": "2024-01-02", "target_player_1_win": 1, "rank_diff": 2},
                {"match_date": "2024-01-04", "target_player_1_win": 0, "rank_diff": 4},
                {"match_date": "2024-01-05", "target_player_1_win": 1, "rank_diff": 5},
            ]
        )

        split = temporal_train_test_split(dataframe, test_size=0.4)

        self.assertEqual(split.train["match_date"].dt.date.astype(str).tolist(), ["2024-01-01", "2024-01-02", "2024-01-03"])
        self.assertEqual(split.test["match_date"].dt.date.astype(str).tolist(), ["2024-01-04", "2024-01-05"])

    def test_leakage_columns_are_not_selected_as_features(self):
        dataframe = pd.DataFrame(
            [
                {
                    "surface": "Hard",
                    "rank_diff": 5,
                    "target_player_1_win": 1,
                    "match_id": 10,
                    "match_date": "2024-01-01",
                    "avg_player_1_odds": 2.0,
                    "market_prob_player_1": 0.5,
                    "player_1_profit_if_bet": 1.0,
                    "atp_score": "6-4 6-4",
                    "atp_minutes": 80,
                }
            ]
        )

        features = selected_feature_columns(dataframe, model_version="v1")

        self.assertEqual(features, ["surface", "rank_diff"])
        self.assertTrue({"avg_player_1_odds", "market_prob_player_1", "atp_score"}.issubset(LEAKAGE_EXCLUDED_COLUMNS))

    def test_v3_selects_odds_features_but_v2_does_not(self):
        dataframe = pd.DataFrame(
            [
                {
                    "surface": "Hard",
                    "rank_diff": 5,
                    "elo_diff": 10,
                    "avg_player_1_odds": 2.0,
                    "avg_player_2_odds": 1.8,
                    "avg_market_prob_player_1": 0.47,
                    "avg_market_prob_player_2": 0.53,
                    "avg_bookmaker_margin": 0.04,
                    "odds_bookmaker_count": 2,
                    "player_1_profit_if_bet": 1.0,
                }
            ]
        )

        v2_features = selected_feature_columns(dataframe, model_version="v2")
        v3_features = selected_feature_columns(dataframe, model_version="v3")

        self.assertNotIn("avg_player_1_odds", v2_features)
        self.assertIn("avg_player_1_odds", v3_features)
        self.assertIn("avg_market_prob_player_1", v3_features)
        self.assertNotIn("player_1_profit_if_bet", v3_features)

    def test_v3_odds_filter_keeps_only_rows_with_valid_odds(self):
        dataframe = pd.DataFrame(
            [
                {
                    "match_date": "2024-01-01",
                    "avg_player_1_odds": 2.0,
                    "avg_player_2_odds": 1.8,
                    "avg_market_prob_player_1": 0.47,
                    "avg_market_prob_player_2": 0.53,
                    "avg_bookmaker_margin": 0.04,
                    "odds_bookmaker_count": 2,
                },
                {
                    "match_date": "2024-01-02",
                    "avg_player_1_odds": None,
                    "avg_player_2_odds": 1.8,
                    "avg_market_prob_player_1": 0.47,
                    "avg_market_prob_player_2": 0.53,
                    "avg_bookmaker_margin": 0.04,
                    "odds_bookmaker_count": 2,
                },
            ]
        )

        filtered = filter_rows_with_valid_odds(dataframe)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["match_date"], "2024-01-01")


if __name__ == "__main__":
    unittest.main()
