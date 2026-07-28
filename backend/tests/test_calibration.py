"""Tests for probability calibration analysis."""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from backend.src.app.ml.model_versioning import calibrator_artifact_path
from backend.src.app.ml.training.calibration import (
    CalibrationConfig,
    OosPredictionBatch,
    apply_calibrator,
    assert_calibrator_train_precedes_eval,
    compute_brier_score,
    compute_calibration_metrics,
    compute_log_loss,
    compute_reliability_bins,
    evaluate_fold_calibration,
    expected_calibration_error,
    fit_calibrator,
    fit_isotonic_calibrator,
    fit_platt_calibrator,
    maximum_calibration_error,
    run_calibration_validation,
    save_calibrator_artifact,
)
from backend.src.app.ml.training.walk_forward import WalkForwardConfig


def _synthetic_dataset(n_days: int = 400, matches_per_day: int = 3) -> pd.DataFrame:
    rows: list[dict] = []
    start = date(2023, 1, 1)
    for day_offset in range(n_days):
        day = start + timedelta(days=day_offset)
        for match_idx in range(matches_per_day):
            rows.append(
                {
                    "match_id": day_offset * matches_per_day + match_idx,
                    "match_date": day.isoformat(),
                    "target_player_1_win": (day_offset + match_idx) % 2,
                    "surface": "Hard" if day_offset % 2 == 0 else "Clay",
                    "rank_diff": (day_offset % 20) - 10,
                    "elo_diff": (day_offset % 30) - 15,
                    "surface_elo_diff": (day_offset % 12) - 6,
                    "rank_points_diff": (day_offset % 40) - 20,
                    "player_1_last_5_win_rate": 0.4 + (day_offset % 5) * 0.05,
                    "player_2_last_5_win_rate": 0.35 + (match_idx % 3) * 0.05,
                    "player_1_last_10_win_rate": 0.45,
                    "player_2_last_10_win_rate": 0.42,
                    "player_1_surface_last_10_win_rate": 0.5,
                    "player_2_surface_last_10_win_rate": 0.48,
                    "player_1_matches_last_14_days": match_idx,
                    "player_2_matches_last_14_days": match_idx + 1,
                    "player_1_days_since_last_match": 3,
                    "player_2_days_since_last_match": 4,
                    "h2h_player_1_wins": 1,
                    "h2h_player_2_wins": 2,
                    "h2h_surface_player_1_wins": 0,
                    "h2h_surface_player_2_wins": 1,
                    "player_1_age": 26,
                    "player_2_age": 28,
                    "age_diff": -2,
                    "player_1_height": 185,
                    "player_2_height": 180,
                    "height_diff": 5,
                    "player_1_hand": "R",
                    "player_2_hand": "L",
                    "atp_surface": "Hard",
                    "atp_tourney_level": "A",
                    "atp_round": "R32",
                    "atp_best_of": 3,
                    "atp_match_found": 1,
                    "avg_player_1_odds": 1.9,
                    "avg_player_2_odds": 2.0,
                    "avg_market_prob_player_1": 0.5,
                    "avg_market_prob_player_2": 0.48,
                    "avg_bookmaker_margin": 0.04,
                    "odds_bookmaker_count": 3,
                    "player_1_profit_if_bet": 0.9,
                    "market_prob_player_1": 0.5,
                }
            )
    return pd.DataFrame(rows)


class CalibrationMetricsTest(unittest.TestCase):
    def test_perfect_calibration_has_low_ece(self):
        y_true = np.array([0, 0, 1, 1, 0, 1, 1, 0, 1, 0])
        y_prob = np.array([0.1, 0.2, 0.8, 0.9, 0.15, 0.85, 0.75, 0.25, 0.95, 0.05])
        metrics = compute_calibration_metrics(y_true, y_prob, n_bins=5, min_bin_samples=1)
        self.assertIsNotNone(metrics.ece)
        self.assertLessEqual(metrics.ece, 0.15)
        self.assertIsNotNone(metrics.brier_score)
        self.assertIsNotNone(metrics.log_loss)

    def test_reliability_bins_flag_insufficient_sample(self):
        y_true = np.array([1, 0, 1, 0, 1])
        y_prob = np.array([0.9, 0.1, 0.85, 0.15, 0.95])
        bins = compute_reliability_bins(y_true, y_prob, n_bins=10, min_bin_samples=30)
        populated = [item for item in bins if item.count > 0]
        self.assertGreater(len(populated), 0)
        for item in populated:
            self.assertTrue(item.insufficient_sample)

    def test_brier_and_log_loss_known_values(self):
        y_true = np.array([1, 0, 1, 0])
        y_prob = np.array([0.9, 0.1, 0.8, 0.2])
        brier = compute_brier_score(y_true, y_prob)
        logloss = compute_log_loss(y_true, y_prob)
        self.assertAlmostEqual(brier, 0.025, places=3)
        self.assertIsNotNone(logloss)
        self.assertGreater(logloss, 0.0)

    def test_ece_mce_from_bins(self):
        y_true = np.array([1, 0, 1, 0, 1, 0])
        y_prob = np.array([0.9, 0.8, 0.85, 0.2, 0.95, 0.15])
        bins = compute_reliability_bins(y_true, y_prob, n_bins=2, min_bin_samples=1)
        ece = expected_calibration_error(bins, len(y_true))
        mce = maximum_calibration_error(bins)
        self.assertIsNotNone(ece)
        self.assertIsNotNone(mce)
        self.assertGreaterEqual(mce, 0.0)


class CalibrationMethodsTest(unittest.TestCase):
    def test_calibrator_artifact_path_under_reports(self):
        path = calibrator_artifact_path(
            model_version="v2",
            model_name="logistic_regression",
            method="platt",
            run_id=7,
        )
        self.assertIn("reports", str(path).replace("\\", "/"))
        self.assertIn("calibration/artifacts", str(path).replace("\\", "/"))
        self.assertIn("calibration_run_7_v2_logistic_regression_platt.pkl", path.name)

    def test_platt_and_isotonic_produce_valid_probabilities(self):
        rng = np.random.default_rng(42)
        y_true = rng.integers(0, 2, size=200)
        y_prob = np.clip(rng.normal(0.5, 0.15, size=200), 0.05, 0.95)
        platt = fit_platt_calibrator(y_true, y_prob)
        iso = fit_isotonic_calibrator(y_true, y_prob)
        platt_out = apply_calibrator("platt", platt, y_prob)
        iso_out = apply_calibrator("isotonic", iso, y_prob)
        self.assertTrue(np.all(platt_out >= 0) and np.all(platt_out <= 1))
        self.assertTrue(np.all(iso_out >= 0) and np.all(iso_out <= 1))

    def test_fit_calibrator_returns_none_for_single_class(self):
        y_true = np.ones(50, dtype=int)
        y_prob = np.linspace(0.1, 0.9, 50)
        self.assertIsNone(fit_calibrator("platt", y_true, y_prob))
        self.assertIsNone(fit_calibrator("isotonic", y_true, y_prob))


class CalibrationAntiLeakageTest(unittest.TestCase):
    def test_calibrator_train_must_precede_eval(self):
        prior = [
            OosPredictionBatch(
                fold_index=0,
                test_start=date(2024, 1, 1),
                test_end=date(2024, 3, 31),
                y_true=np.array([1, 0]),
                prob_raw=np.array([0.7, 0.3]),
                match_dates=np.array([date(2024, 2, 1), date(2024, 3, 1)]),
            )
        ]
        eval_ok = OosPredictionBatch(
            fold_index=1,
            test_start=date(2024, 4, 1),
            test_end=date(2024, 6, 30),
            y_true=np.array([1, 0]),
            prob_raw=np.array([0.6, 0.4]),
            match_dates=np.array([date(2024, 5, 1), date(2024, 6, 1)]),
        )
        assert_calibrator_train_precedes_eval(prior, eval_ok)

        eval_bad = OosPredictionBatch(
            fold_index=1,
            test_start=date(2024, 3, 15),
            test_end=date(2024, 6, 30),
            y_true=np.array([1, 0]),
            prob_raw=np.array([0.6, 0.4]),
            match_dates=np.array([date(2024, 4, 1), date(2024, 5, 1)]),
        )
        with self.assertRaises(ValueError):
            assert_calibrator_train_precedes_eval(prior, eval_bad)

    def test_evaluate_fold_calibration_respects_temporal_order(self):
        config = CalibrationConfig(
            n_bins=5,
            min_bin_samples=1,
            min_calibrator_train_samples=2,
            methods=("raw", "platt", "isotonic"),
        )
        prior = [
            OosPredictionBatch(
                fold_index=0,
                test_start=date(2024, 1, 1),
                test_end=date(2024, 3, 31),
                y_true=np.array([1, 0, 1, 0, 1, 0]),
                prob_raw=np.array([0.7, 0.3, 0.65, 0.35, 0.8, 0.2]),
                match_dates=np.array(
                    [date(2024, 2, d) for d in (1, 5, 10, 15, 20, 25)]
                ),
            )
        ]
        eval_batch = OosPredictionBatch(
            fold_index=1,
            test_start=date(2024, 4, 1),
            test_end=date(2024, 6, 30),
            y_true=np.array([1, 0, 1, 0]),
            prob_raw=np.array([0.75, 0.25, 0.6, 0.4]),
            match_dates=np.array([date(2024, 5, d) for d in (1, 10, 20, 30)]),
        )
        outcome = evaluate_fold_calibration(prior, eval_batch, config)
        self.assertIn("raw", outcome.methods)
        self.assertIn("platt", outcome.methods)
        self.assertIn("isotonic", outcome.methods)
        self.assertEqual(outcome.calibrator_train_samples, 6)


class CalibrationIntegrationTest(unittest.TestCase):
    def test_end_to_end_on_synthetic_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            reports = Path(tmp) / "reports"
            processed.mkdir()
            reports.mkdir()
            dataset = _synthetic_dataset(n_days=250, matches_per_day=2)
            dataset.to_csv(processed / "tennis_winner_dataset_v2.csv", index=False)

            wf = WalkForwardConfig(
                mode="expanding",
                initial_train_days=80,
                test_days=25,
                step_days=25,
                min_train_rows=20,
                min_test_rows=5,
                embargo_days=0,
            )
            config = CalibrationConfig(
                n_bins=5,
                min_bin_samples=3,
                min_calibrator_train_samples=10,
                methods=("raw", "platt", "isotonic"),
                walk_forward=wf,
            )
            result = run_calibration_validation(
                config,
                versions=("v2",),
                model_names=("logistic_regression",),
                processed_dir=processed,
                persist_artifacts=False,
            )
            self.assertGreaterEqual(result.summary["models_with_oos"], 1)
            model = result.models[0]
            self.assertGreater(model.oos_samples_total, 0)
            self.assertIn("raw", model.aggregate)
            self.assertIn("comparison", model.to_dict())

    def test_reproducibility_same_seed_same_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            processed.mkdir()
            dataset = _synthetic_dataset(n_days=200, matches_per_day=2)
            dataset.to_csv(processed / "tennis_winner_dataset_v2.csv", index=False)

            wf = WalkForwardConfig(
                mode="expanding",
                initial_train_days=70,
                test_days=20,
                step_days=20,
                min_train_rows=15,
                min_test_rows=5,
                random_state=42,
            )
            config = CalibrationConfig(
                n_bins=5,
                min_bin_samples=2,
                min_calibrator_train_samples=8,
                walk_forward=wf,
            )
            first = run_calibration_validation(
                config,
                versions=("v2",),
                model_names=("logistic_regression",),
                processed_dir=processed,
                persist_artifacts=False,
            )
            second = run_calibration_validation(
                config,
                versions=("v2",),
                model_names=("logistic_regression",),
                processed_dir=processed,
                persist_artifacts=False,
            )
            raw_first = first.models[0].aggregate["raw"]
            raw_second = second.models[0].aggregate["raw"]
            self.assertEqual(raw_first.brier_score, raw_second.brier_score)
            self.assertEqual(raw_first.log_loss, raw_second.log_loss)
            self.assertEqual(raw_first.ece, raw_second.ece)


class CalibrationArtifactResilienceTest(unittest.TestCase):
    def test_metrics_kept_when_artifact_save_raises_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            processed.mkdir()
            dataset = _synthetic_dataset(n_days=250, matches_per_day=2)
            dataset.to_csv(processed / "tennis_winner_dataset_v2.csv", index=False)

            wf = WalkForwardConfig(
                mode="expanding",
                initial_train_days=80,
                test_days=25,
                step_days=25,
                min_train_rows=20,
                min_test_rows=5,
                embargo_days=0,
            )
            config = CalibrationConfig(
                n_bins=5,
                min_bin_samples=3,
                min_calibrator_train_samples=10,
                methods=("raw", "platt", "isotonic"),
                walk_forward=wf,
            )
            with unittest.mock.patch(
                "backend.src.app.ml.training.calibration.save_calibrator_artifact",
                return_value=None,
            ):
                result = run_calibration_validation(
                    config,
                    versions=("v2",),
                    model_names=("logistic_regression",),
                    processed_dir=processed,
                    run_id=99,
                    persist_artifacts=True,
                )
            model = result.models[0]
            self.assertGreater(model.oos_samples_total, 0)
            self.assertIn("raw", model.aggregate)
            self.assertIsNotNone(model.aggregate["raw"].ece)
            self.assertEqual(model.artifacts, {})
            warnings = model.comparison.get("artifact_warnings", [])
            self.assertTrue(warnings)

    def test_save_calibrator_artifact_swallows_read_only_filesystem(self):
        with unittest.mock.patch.object(Path, "mkdir", side_effect=OSError(30, "Read-only file system")):
            path = save_calibrator_artifact(
                object(),
                model_version="v2",
                model_name="logistic_regression",
                method="platt",
                run_id=1,
            )
        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
