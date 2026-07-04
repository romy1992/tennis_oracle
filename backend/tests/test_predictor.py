import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd
from sklearn.linear_model import LogisticRegression

from backend.src.app.ml.datasets.dataset_builder import (
    LegacyMatchRow,
    MISSING_RANK_VALUE,
)
from backend.src.app.ml.prediction.predictor import (
    PreMatchFeatureBuilder,
    _patch_artifact_for_runtime_compat,
    predict_fixture,
)
from backend.src.entity.next_fixture import NextFixture


class PredictorTest(unittest.TestCase):
    def _builder_with_history(self) -> PreMatchFeatureBuilder:
        builder = PreMatchFeatureBuilder()
        matches = [
            LegacyMatchRow(
                match_id=1,
                match_date=date(2026, 6, 1),
                surface="Hard",
                player_1_id=10,
                player_2_id=20,
                target_player_1_win=1,
            ),
            LegacyMatchRow(
                match_id=2,
                match_date=date(2026, 6, 10),
                surface="Hard",
                player_1_id=10,
                player_2_id=30,
                target_player_1_win=0,
            ),
        ]
        builder._ingest_history(matches)
        return builder

    def test_v1_feature_row_has_form_and_h2h_without_elo(self):
        builder = self._builder_with_history()
        row, warnings, features_available = builder.build_feature_row(
            event_key=100,
            match_date=date(2026, 6, 21),
            surface="Hard",
            player_1_id=10,
            player_2_id=20,
            model_version="v1",
        )
        self.assertTrue(features_available)
        self.assertEqual(row["h2h_player_1_wins"], 1)
        self.assertIsNone(row["player_1_elo"])
        self.assertIn("player_1_last_5_win_rate", row)

    def test_v2_feature_row_includes_elo_and_rank(self):
        builder = self._builder_with_history()
        row, _warnings, features_available = builder.build_feature_row(
            event_key=100,
            match_date=date(2026, 6, 21),
            surface="Hard",
            player_1_id=10,
            player_2_id=20,
            model_version="v2",
        )
        self.assertTrue(features_available)
        self.assertIn("elo_diff", row)
        self.assertIn("rank_diff", row)
        self.assertEqual(row["player_1_rank"], MISSING_RANK_VALUE)

    @patch("backend.src.app.ml.prediction.predictor._load_model_artifact")
    def test_predict_fixture_returns_probability(self, mock_load_model):
        builder = self._builder_with_history()
        mock_load_model.return_value = {
            "feature_columns": ["surface", "rank_diff", "h2h_player_1_wins"],
            "pipeline": type(
                "Pipeline",
                (),
                {
                    "predict_proba": lambda _self, _x: [[0.4, 0.6]],
                },
            )(),
        }
        fixture = NextFixture(
            event_key=100,
            event_date=date(2026, 6, 21),
            surface="Hard",
            first_player_key=10,
            second_player_key=20,
            event_first_player="A",
            event_second_player="B",
        )
        result = predict_fixture(
            fixture,
            feature_builder=builder,
            model_version="v1",
        )
        self.assertEqual(result["event_key"], 100)
        self.assertAlmostEqual(result["prob_player_1_win"], 0.6)
        self.assertEqual(result["predicted_winner"], "First Player")

    def test_runtime_patch_restores_missing_logistic_multi_class(self):
        model = LogisticRegression()
        if hasattr(model, "multi_class"):
            delattr(model, "multi_class")

        artifact = {"pipeline": model}
        _patch_artifact_for_runtime_compat(artifact)

        self.assertTrue(hasattr(model, "multi_class"))
        self.assertEqual(model.multi_class, "auto")


if __name__ == "__main__":
    unittest.main()
