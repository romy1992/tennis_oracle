"""Tests for the Fase 3 v4 ensemble (voting + stacking) exploration script."""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backend.src.app.ml.training.train_v4_ensemble import (
    BASE_ALGORITHMS,
    RESULTS_FILENAME,
    build_base_estimators,
    build_tuned_estimator,
    load_best_params,
    run_ensemble,
)


def _synthetic_v3_dataset(n_days: int = 220, matches_per_day: int = 3) -> pd.DataFrame:
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


class LoadBestParamsTest(unittest.TestCase):
    def test_falls_back_when_report_missing(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            params, source = load_best_params(tmp_dir, "xgboost")
            self.assertIn("max_depth", params)
            self.assertIn("fallback", source)

    def test_reads_and_strips_model_prefix_from_search_report(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            reports_dir = Path(tmp_dir)
            fake_report = {
                "generated_at": "2026-08-07T00:00:00Z",
                "algorithms": {
                    "logistic_regression": {
                        "best_params": {"model__C": 0.05, "model__class_weight": "balanced"},
                    }
                },
            }
            (reports_dir / "v4_grid_search_results.json").write_text(json.dumps(fake_report), encoding="utf-8")

            params, source = load_best_params(reports_dir, "logistic_regression")
            self.assertEqual(params, {"C": 0.05, "class_weight": "balanced"})
            self.assertNotIn("fallback", source)


class BuildTunedEstimatorTest(unittest.TestCase):
    def test_builds_expected_types(self):
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from xgboost import XGBClassifier

        self.assertIsInstance(build_tuned_estimator("logistic_regression", {"C": 1.0}), LogisticRegression)
        self.assertIsInstance(build_tuned_estimator("xgboost", {"n_estimators": 50}), XGBClassifier)
        self.assertIsInstance(
            build_tuned_estimator("hist_gradient_boosting", {"max_iter": 50}), HistGradientBoostingClassifier
        )
        with self.assertRaises(ValueError):
            build_tuned_estimator("unknown_algo", {})


class BuildBaseEstimatorsTest(unittest.TestCase):
    def test_returns_three_base_algorithms_with_provenance(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            estimators, provenance = build_base_estimators(tmp_dir)

            names = [name for name, _ in estimators]
            self.assertEqual(names, BASE_ALGORITHMS)
            self.assertEqual(set(provenance.keys()), set(BASE_ALGORITHMS))
            for info in provenance.values():
                self.assertIn("params_used", info)
                self.assertIn("source", info)


class RunEnsembleEndToEndTest(unittest.TestCase):
    def test_quick_run_produces_report_with_expected_keys(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            models_dir = Path(tmp_dir) / "models" / "v4_ensemble"
            processed_dir.mkdir(parents=True, exist_ok=True)

            dataframe = _synthetic_v3_dataset()
            dataset_path = processed_dir / "tennis_winner_dataset_with_odds_v3.csv"
            dataframe.to_csv(dataset_path, index=False)

            report = run_ensemble(
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                models_dir=models_dir,
                quick=True,
                n_jobs=1,
            )

            self.assertEqual(set(report["ensembles"].keys()), {"voting_soft", "stacking"})
            for ensemble in report["ensembles"].values():
                self.assertIn("test_metrics", ensemble)
                self.assertIn("roc_auc", ensemble["test_metrics"])
                self.assertTrue(Path(ensemble["model_path"]).exists())

            self.assertIn("meta_learner_coefficients", report["ensembles"]["stacking"])
            self.assertEqual(
                set(report["ensembles"]["stacking"]["meta_learner_coefficients"].keys()), set(BASE_ALGORITHMS)
            )

            self.assertIn(report["winner_overall"], set(report["ensembles"].keys()) | {"single:no_data"})

            results_path = reports_dir / RESULTS_FILENAME
            self.assertTrue(results_path.exists())
            with results_path.open("r", encoding="utf-8") as results_file:
                persisted = json.load(results_file)
            self.assertEqual(persisted["winner_overall"], report["winner_overall"])
            # Il registry ufficiale non deve essere toccato dallo script esplorativo.
            self.assertFalse((reports_dir / "model_registry.json").exists())
            self.assertFalse((reports_dir / "model_comparison.json").exists())


if __name__ == "__main__":
    unittest.main()
