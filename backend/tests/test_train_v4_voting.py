"""Tests for the Fase 3 v4 voting-ensemble (tutti gli algoritmi della Fase 1) script."""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backend.src.app.ml.training.train_v4_search import build_param_grids
from backend.src.app.ml.training.train_v4_voting import (
    SEARCH_RESULTS_FILENAME,
    VOTING_RESULTS_FILENAME,
    WEIGHT_STRATEGIES,
    _instantiate_estimator,
    _weight_vector,
    run_voting,
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


def _write_fake_search_report(reports_dir: Path) -> None:
    """Simula un report Fase 1 (v4_grid_search_results.json) con i 5 algoritmi."""
    grids = build_param_grids(quick=True)
    algorithms: dict[str, dict] = {}
    for name, grid_list in grids.items():
        combination = grid_list[0]
        best_params = {key: values[0] for key, values in combination.items()}
        algorithms[name] = {
            "best_params": best_params,
            "cv_best_roc_auc": 0.6,
            "test_metrics": {"roc_auc": 0.6, "log_loss": 0.6, "accuracy": 0.5},
            "model_path": "unused.pkl",
        }
    report = {
        "generated_at": "2026-08-07T00:00:00Z",
        "split": {"dev_size": 0.8},
        "algorithms": algorithms,
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / SEARCH_RESULTS_FILENAME).write_text(json.dumps(report), encoding="utf-8")


class InstantiateEstimatorTest(unittest.TestCase):
    def test_builds_expected_types_for_all_five_algorithms(self):
        from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier

        self.assertIsInstance(_instantiate_estimator("logistic_regression", {"model__C": 1.0}), LogisticRegression)
        self.assertIsInstance(
            _instantiate_estimator("random_forest", {"model__n_estimators": 50}), RandomForestClassifier
        )
        self.assertIsInstance(
            _instantiate_estimator("hist_gradient_boosting", {"model__max_iter": 50}),
            HistGradientBoostingClassifier,
        )
        self.assertIsInstance(_instantiate_estimator("xgboost", {"model__n_estimators": 50}), XGBClassifier)
        self.assertIsInstance(_instantiate_estimator("lightgbm", {"model__n_estimators": 50}), LGBMClassifier)

    def test_xgboost_and_lightgbm_use_fixed_base_params(self):
        xgb = _instantiate_estimator("xgboost", {"model__n_estimators": 42})
        xgb_params = xgb.get_params()
        self.assertEqual(xgb_params["eval_metric"], "logloss")
        self.assertEqual(xgb_params["random_state"], 42)
        self.assertEqual(xgb_params["n_estimators"], 42)

        lgbm = _instantiate_estimator("lightgbm", {"model__n_estimators": 42})
        lgbm_params = lgbm.get_params()
        self.assertEqual(lgbm_params["verbosity"], -1)
        self.assertEqual(lgbm_params["random_state"], 42)
        self.assertEqual(lgbm_params["n_estimators"], 42)

    def test_unknown_algorithm_raises(self):
        with self.assertRaises(ValueError):
            _instantiate_estimator("unknown_algo", {})


class WeightVectorTest(unittest.TestCase):
    def test_uniform_weights_are_all_one(self):
        weights = _weight_vector("uniform", ["a", "b", "c"], {"a": 0.9, "b": 0.5, "c": 0.7})
        self.assertEqual(weights, [1.0, 1.0, 1.0])

    def test_favor_best_doubles_top_cv_score(self):
        weights = _weight_vector("favor_best", ["a", "b", "c"], {"a": 0.9, "b": 0.5, "c": 0.7})
        self.assertEqual(weights, [2.0, 1.0, 1.0])

    def test_cv_score_weighted_uses_scores_directly(self):
        weights = _weight_vector("cv_score_weighted", ["a", "b"], {"a": 0.9, "b": 0.5})
        self.assertEqual(weights, [0.9, 0.5])

    def test_unknown_strategy_raises(self):
        with self.assertRaises(ValueError):
            _weight_vector("unknown", ["a"], {"a": 0.5})


class RunVotingEndToEndTest(unittest.TestCase):
    def test_run_produces_report_with_all_five_algorithms(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            models_dir = Path(tmp_dir) / "models" / "v4_voting"
            processed_dir.mkdir(parents=True, exist_ok=True)

            dataframe = _synthetic_v3_dataset()
            dataset_path = processed_dir / "tennis_winner_dataset_with_odds_v3.csv"
            dataframe.to_csv(dataset_path, index=False)
            _write_fake_search_report(reports_dir)

            report = run_voting(
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                models_dir=models_dir,
            )

            self.assertEqual(
                set(report["algorithms_used"]),
                {"logistic_regression", "random_forest", "hist_gradient_boosting", "xgboost", "lightgbm"},
            )
            self.assertEqual(set(report["strategies"].keys()), set(WEIGHT_STRATEGIES.keys()))
            self.assertIn(report["best_strategy"], WEIGHT_STRATEGIES)
            self.assertTrue(Path(report["best_voting_model_path"]).exists())

            results_path = reports_dir / VOTING_RESULTS_FILENAME
            self.assertTrue(results_path.exists())
            with results_path.open("r", encoding="utf-8") as results_file:
                persisted = json.load(results_file)
            self.assertEqual(persisted["best_strategy"], report["best_strategy"])
            # Il registry ufficiale non deve essere toccato dallo script esplorativo.
            self.assertFalse((reports_dir / "model_registry.json").exists())
            self.assertFalse((reports_dir / "model_comparison.json").exists())

    def test_raises_clear_error_when_search_report_missing(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            with self.assertRaises(FileNotFoundError):
                run_voting(
                    processed_dir=Path(tmp_dir) / "processed",
                    reports_dir=Path(tmp_dir) / "reports",
                    models_dir=Path(tmp_dir) / "models",
                )


if __name__ == "__main__":
    unittest.main()
