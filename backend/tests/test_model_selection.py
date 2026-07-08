import json
import tempfile
import unittest
from pathlib import Path

from backend.src.app.ml.model_selection import select_best_model


class ModelSelectionTest(unittest.TestCase):
    def test_selects_highest_roc_auc_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            (reports_dir / "baseline_v2_metrics.json").write_text(
                json.dumps(
                    {
                        "logistic_regression": {"accuracy": 0.8, "roc_auc": 0.7},
                        "random_forest": {"accuracy": 0.75, "roc_auc": 0.9},
                    }
                ),
                encoding="utf-8",
            )

            selected = select_best_model("v2", reports_dir=reports_dir)

        self.assertEqual(selected.model_name, "random_forest")
        self.assertEqual(selected.metric_name, "roc_auc")

    def test_reads_nested_models_report_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            (reports_dir / "baseline_v2_metrics.json").write_text(
                json.dumps(
                    {
                        "model_version": "v2",
                        "models": {
                            "logistic_regression": {"accuracy": 0.68, "roc_auc": 0.75},
                            "random_forest": {"accuracy": 0.69, "roc_auc": 0.76},
                        },
                    }
                ),
                encoding="utf-8",
            )

            selected = select_best_model("v2", reports_dir=reports_dir)

        self.assertEqual(selected.model_name, "random_forest")
        self.assertEqual(selected.metric_name, "roc_auc")

    def test_uses_lowest_log_loss_when_only_log_loss_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            (reports_dir / "baseline_metrics.json").write_text(
                json.dumps(
                    {
                        "logistic_regression": {"log_loss": 0.6},
                        "random_forest": {"log_loss": 0.4},
                    }
                ),
                encoding="utf-8",
            )

            selected = select_best_model("v1", reports_dir=reports_dir)

        self.assertEqual(selected.model_name, "random_forest")
        self.assertEqual(selected.metric_name, "log_loss")

    def test_supports_v3_metrics_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp)
            (reports_dir / "baseline_v3_metrics.json").write_text(
                json.dumps(
                    {
                        "model_version": "v3",
                        "models": {
                            "logistic_regression": {"accuracy": 0.7, "roc_auc": 0.8},
                            "random_forest": {"accuracy": 0.72, "roc_auc": 0.78},
                        },
                    }
                ),
                encoding="utf-8",
            )

            selected = select_best_model("v3", reports_dir=reports_dir)

        self.assertEqual(selected.model_version, "v3")
        self.assertEqual(selected.model_name, "logistic_regression")


if __name__ == "__main__":
    unittest.main()
