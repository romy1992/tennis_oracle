"""Tests for temporal walk-forward validation."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backend.src.app.ml.training.walk_forward import (
    WalkForwardConfig,
    assert_no_temporal_overlap,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    run_walk_forward_for_version,
    slice_fold_frames,
    write_walk_forward_report,
    run_walk_forward_validation,
)


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


class WalkForwardTemporalTest(unittest.TestCase):
    def test_prepare_sorts_chronologically_without_shuffle(self):
        dataframe = pd.DataFrame(
            [
                {"match_date": "2024-01-03", "target_player_1_win": 1, "rank_diff": 1},
                {"match_date": "2024-01-01", "target_player_1_win": 0, "rank_diff": 2},
                {"match_date": "2024-01-02", "target_player_1_win": 1, "rank_diff": 3},
            ]
        )
        prepared = prepare_temporal_dataframe(dataframe, model_version="v1")
        self.assertEqual(
            prepared["match_date"].dt.date.astype(str).tolist(),
            ["2024-01-01", "2024-01-02", "2024-01-03"],
        )

    def test_fold_windows_are_contiguous_and_non_overlapping(self):
        dataframe = _synthetic_dataset(n_days=300, matches_per_day=1)
        config = WalkForwardConfig(
            mode="expanding",
            initial_train_days=100,
            test_days=30,
            step_days=30,
            embargo_days=0,
            min_train_rows=10,
            min_test_rows=5,
        )
        folds = generate_walk_forward_folds(dataframe, config)
        self.assertGreaterEqual(len(folds), 2)
        for fold in folds:
            self.assertLess(fold.train_end, fold.test_start)
            self.assertLessEqual(fold.test_start, fold.test_end)
            train, test = slice_fold_frames(dataframe, fold)
            assert_no_temporal_overlap(train, test)
            if not train.empty and not test.empty:
                self.assertLess(
                    pd.to_datetime(train["match_date"]).max(),
                    pd.to_datetime(test["match_date"]).min(),
                )

    def test_rolling_mode_keeps_bounded_train_window(self):
        dataframe = _synthetic_dataset(n_days=250, matches_per_day=1)
        config = WalkForwardConfig(
            mode="rolling",
            initial_train_days=60,
            test_days=20,
            step_days=20,
            min_train_rows=5,
            min_test_rows=3,
        )
        folds = generate_walk_forward_folds(dataframe, config)
        self.assertGreaterEqual(len(folds), 2)
        for fold in folds:
            span = (fold.train_end - fold.train_start).days + 1
            self.assertLessEqual(span, config.initial_train_days)

    def test_expanding_mode_train_start_stays_fixed(self):
        dataframe = _synthetic_dataset(n_days=250, matches_per_day=1)
        config = WalkForwardConfig(
            mode="expanding",
            initial_train_days=80,
            test_days=20,
            step_days=20,
            min_train_rows=5,
            min_test_rows=3,
        )
        folds = generate_walk_forward_folds(dataframe, config)
        starts = {fold.train_start for fold in folds}
        self.assertEqual(len(starts), 1)

    def test_reproducibility_same_config_same_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            processed = tmp_path / "processed"
            reports = tmp_path / "reports"
            processed.mkdir()
            reports.mkdir()
            dataset = _synthetic_dataset(n_days=220, matches_per_day=2)
            dataset_path = processed / "tennis_winner_dataset_v2.csv"
            dataset.to_csv(dataset_path, index=False)

            config = WalkForwardConfig(
                mode="expanding",
                initial_train_days=90,
                test_days=30,
                step_days=30,
                min_train_rows=40,
                min_test_rows=10,
                random_state=42,
            )
            first = run_walk_forward_for_version(
                "v2",
                config,
                processed_dir=processed,
                reports_dir=reports,
                model_names=("logistic_regression",),
            )
            second = run_walk_forward_for_version(
                "v2",
                config,
                processed_dir=processed,
                reports_dir=reports,
                model_names=("logistic_regression",),
            )
            self.assertEqual(first.aggregate_metrics, second.aggregate_metrics)
            self.assertEqual(
                [fold.status for fold in first.folds],
                [fold.status for fold in second.folds],
            )

    def test_does_not_overwrite_holdout_metrics_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            processed = tmp_path / "processed"
            reports = tmp_path / "reports"
            processed.mkdir()
            reports.mkdir()
            holdout = reports / "baseline_v2_metrics.json"
            holdout.write_text(json.dumps({"models": {"logistic_regression": {"accuracy": 0.99}}}), encoding="utf-8")
            original = holdout.read_text(encoding="utf-8")

            dataset = _synthetic_dataset(n_days=180, matches_per_day=2)
            dataset.to_csv(processed / "tennis_winner_dataset_v2.csv", index=False)

            config = WalkForwardConfig(
                mode="expanding",
                initial_train_days=60,
                test_days=20,
                step_days=20,
                min_train_rows=20,
                min_test_rows=5,
            )
            result = run_walk_forward_validation(
                config,
                versions=("v2",),
                processed_dir=processed,
                reports_dir=reports,
                model_names=("logistic_regression",),
            )
            write_walk_forward_report(result, reports_dir=reports, run_id=1)
            self.assertEqual(holdout.read_text(encoding="utf-8"), original)
            self.assertTrue((reports / "walk_forward" / "walk_forward_latest.json").exists())
            self.assertTrue(result.summary["holdout_metrics_unchanged"])
            self.assertTrue(result.summary["public_model_unchanged"])
            self.assertFalse(result.summary["official_metrics_shuffled"])
            self.assertIn("official_contenders", result.summary)

    def test_insufficient_data_marks_skipped_fold(self):
        dataframe = _synthetic_dataset(n_days=120, matches_per_day=1)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            processed = tmp_path / "processed"
            reports = tmp_path / "reports"
            processed.mkdir()
            reports.mkdir()
            dataframe.to_csv(processed / "tennis_winner_dataset_v2.csv", index=False)
            config = WalkForwardConfig(
                mode="expanding",
                initial_train_days=40,
                test_days=15,
                step_days=15,
                min_train_rows=10_000,  # force skip
                min_test_rows=1,
            )
            result = run_walk_forward_for_version(
                "v2",
                config,
                processed_dir=processed,
                reports_dir=reports,
                model_names=("logistic_regression",),
            )
            self.assertTrue(result.folds)
            self.assertTrue(all(fold.status == "skipped_insufficient_data" for fold in result.folds))

    def test_official_benchmarks_use_common_sample_and_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            processed = tmp_path / "processed"
            reports = tmp_path / "reports"
            processed.mkdir()
            reports.mkdir()
            dataset = _synthetic_dataset(n_days=220, matches_per_day=2)
            dataset.to_csv(processed / "tennis_winner_dataset_v2.csv", index=False)

            config = WalkForwardConfig(
                mode="expanding",
                initial_train_days=90,
                test_days=30,
                step_days=30,
                min_train_rows=40,
                min_test_rows=10,
                random_state=42,
            )
            result = run_walk_forward_for_version(
                "v2",
                config,
                processed_dir=processed,
                reports_dir=reports,
                model_names=("logistic_regression", "random_forest"),
            )
            completed = [item for item in result.folds if item.status == "completed"]
            all_names = {item.model_name for item in result.folds}
            benchmark_names = {
                "market_favorite",
                "market_no_vig",
                "atp_ranking",
                "elo",
            }
            self.assertTrue(benchmark_names.issubset(all_names))
            self.assertIn("official_benchmarks", result.aggregate_metrics)

            logistic_outcomes = [item for item in completed if item.model_name == "logistic_regression"]
            self.assertTrue(logistic_outcomes)
            sample_meta = logistic_outcomes[0].coverage.get("official_benchmark_sample")
            assert isinstance(sample_meta, dict)
            self.assertIn("sample_mismatch_detected", sample_meta)

            benchmark_outcomes = [item for item in result.folds if item.model_name == "market_no_vig"]
            self.assertTrue(benchmark_outcomes)
            if benchmark_outcomes[0].status == "completed":
                official_payload = benchmark_outcomes[0].metrics.get("official_benchmark")
                assert isinstance(official_payload, dict)
                self.assertIn("brier_score", official_payload)
                self.assertIn("max_drawdown", official_payload)
            else:
                self.assertIsNotNone(benchmark_outcomes[0].skip_reason)


if __name__ == "__main__":
    unittest.main()
