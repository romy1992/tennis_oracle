"""Tests for the Fase 1 v4 grid-search exploration script."""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backend.src.app.ml.training.train_v4_search import (
    RESULTS_FILENAME,
    build_base_estimators,
    build_param_grids,
    run_search,
    _grid_size,
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


class BuildParamGridsTest(unittest.TestCase):
    def test_quick_grids_have_single_combination_per_algorithm(self):
        grids = build_param_grids(quick=True)

        self.assertEqual(
            set(grids.keys()),
            {"logistic_regression", "random_forest", "hist_gradient_boosting", "xgboost", "lightgbm"},
        )
        for name, grid in grids.items():
            self.assertEqual(_grid_size(grid), 1, f"{name} dovrebbe avere 1 sola combinazione in quick mode")

    def test_full_grids_have_multiple_combinations(self):
        grids = build_param_grids(quick=False)

        for name, grid in grids.items():
            self.assertGreater(_grid_size(grid), 1, f"{name} dovrebbe avere piu' di 1 combinazione in full mode")

    def test_logistic_regression_grid_uses_l1_ratio_not_deprecated_penalty(self):
        # sklearn >=1.8 deprecates 'penalty' in favore di 'l1_ratio'; verifichiamo che
        # la griglia non passi piu' 'model__penalty' (altrimenti FutureWarning/rimozione in 1.10).
        grids = build_param_grids(quick=False)
        for combination in grids["logistic_regression"]:
            self.assertNotIn("model__penalty", combination)


class BuildBaseEstimatorsTest(unittest.TestCase):
    def test_returns_expected_algorithm_keys_and_types(self):
        from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier

        estimators = build_base_estimators()

        self.assertEqual(
            set(estimators.keys()),
            {"logistic_regression", "random_forest", "hist_gradient_boosting", "xgboost", "lightgbm"},
        )
        self.assertIsInstance(estimators["logistic_regression"], LogisticRegression)
        self.assertIsInstance(estimators["random_forest"], RandomForestClassifier)
        self.assertIsInstance(estimators["hist_gradient_boosting"], HistGradientBoostingClassifier)
        self.assertIsInstance(estimators["xgboost"], XGBClassifier)
        self.assertIsInstance(estimators["lightgbm"], LGBMClassifier)
        self.assertEqual(estimators["random_forest"].random_state, 42)
        self.assertEqual(estimators["hist_gradient_boosting"].random_state, 42)
        self.assertEqual(estimators["xgboost"].random_state, 42)
        self.assertEqual(estimators["lightgbm"].random_state, 42)


class GridSizeTest(unittest.TestCase):
    def test_counts_combinations_across_alternative_grids(self):
        grid = [
            {"a": [1, 2], "b": [1, 2, 3]},  # 6
            {"a": [1]},  # 1
        ]
        self.assertEqual(_grid_size(grid), 7)


class RunSearchEndToEndTest(unittest.TestCase):
    def test_quick_run_produces_report_with_expected_keys(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            models_dir = Path(tmp_dir) / "models" / "v4_search"
            processed_dir.mkdir(parents=True, exist_ok=True)

            dataframe = _synthetic_v3_dataset()
            dataset_path = processed_dir / "tennis_winner_dataset_with_odds_v3.csv"
            dataframe.to_csv(dataset_path, index=False)

            report = run_search(
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                models_dir=models_dir,
                quick=True,
                n_jobs=1,
            )

            self.assertEqual(set(report["algorithms"].keys()), {
                "logistic_regression",
                "random_forest",
                "hist_gradient_boosting",
                "xgboost",
                "lightgbm",
            })
            self.assertIn(report["winner"], report["algorithms"].keys())
            for algo in report["algorithms"].values():
                self.assertIn("test_metrics", algo)
                self.assertIn("roc_auc", algo["test_metrics"])
                self.assertTrue(Path(algo["model_path"]).exists())

            results_path = reports_dir / RESULTS_FILENAME
            self.assertTrue(results_path.exists())
            with results_path.open("r", encoding="utf-8") as results_file:
                persisted = json.load(results_file)
            self.assertEqual(persisted["winner"], report["winner"])
            # Il registry ufficiale non deve essere toccato dallo script esplorativo.
            self.assertFalse((reports_dir / "model_registry.json").exists())
            self.assertFalse((reports_dir / "model_comparison.json").exists())


if __name__ == "__main__":
    unittest.main()




