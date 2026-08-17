import unittest
from pathlib import Path

import pandas as pd

from backend.src.app.ml.training.train_first_set_winner_serve_stats_experiment import (
    ALLOWED_FEATURE_COLUMNS_SERVE_STATS,
    _load_baseline_comparison,
    selected_feature_columns_experiment,
)


class SelectedFeatureColumnsExperimentTest(unittest.TestCase):
    def test_includes_serve_stats_columns_when_present(self):
        columns = {column: [0] for column in ALLOWED_FEATURE_COLUMNS_SERVE_STATS}
        columns["match_id"] = [1]
        dataframe = pd.DataFrame(columns)

        selected = selected_feature_columns_experiment(dataframe)

        self.assertIn("player_1_serve_pts_won_pct_last10", selected)
        self.assertIn("elo_diff", selected)
        self.assertNotIn("match_id", selected)

    def test_missing_columns_are_simply_excluded(self):
        dataframe = pd.DataFrame({"surface": ["Hard"], "elo_diff": [10.0]})
        selected = selected_feature_columns_experiment(dataframe)
        self.assertEqual(selected, ["surface", "elo_diff"])


class LoadBaselineComparisonTest(unittest.TestCase):
    def test_missing_report_returns_none(self, tmp_path: Path | None = None):
        self.assertIsNone(_load_baseline_comparison("C:/definitely/not/a/real/dir/xyz"))


if __name__ == "__main__":
    unittest.main()

