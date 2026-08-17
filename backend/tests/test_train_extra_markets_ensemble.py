"""Tests for extra-markets ensemble experiment helpers."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

import pandas as pd

from backend.src.app.ml.training.train_extra_markets_ensemble import (
    build_tuned_estimator,
    select_top_algorithms,
)


class SelectTopAlgorithmsTest(unittest.TestCase):
    def test_orders_by_roc_auc_then_roi(self):
        algorithms = {
            "a": {"test_metrics": {"roc_auc": 0.70, "value_bet": {"roi": -0.10}}},
            "b": {"test_metrics": {"roc_auc": 0.72, "value_bet": {"roi": -0.08}}},
            "c": {"test_metrics": {"roc_auc": 0.72, "value_bet": {"roi": -0.02}}},
            "d": {"test_metrics": {"roc_auc": 0.65, "value_bet": {"roi": 0.01}}},
        }
        self.assertEqual(select_top_algorithms(algorithms, top_n=3), ["c", "b", "a"])


class BuildTunedEstimatorTest(unittest.TestCase):
    def test_strips_model_prefix_and_builds_logistic(self):
        estimator = build_tuned_estimator(
            "logistic_regression",
            {"model__C": 0.1, "model__max_iter": 500, "model__solver": "lbfgs"},
        )
        self.assertEqual(estimator.C, 0.1)
        self.assertEqual(estimator.max_iter, 500)


class SyntheticMarketFrameHelper:
    @staticmethod
    def first_set_frame(n_days: int = 120, matches_per_day: int = 4) -> pd.DataFrame:
        rows: list[dict] = []
        start = date(2024, 1, 1)
        for day_offset in range(n_days):
            day = start + timedelta(days=day_offset)
            for match_idx in range(matches_per_day):
                rows.append(
                    {
                        "match_id": day_offset * matches_per_day + match_idx,
                        "match_date": day.isoformat(),
                        "target_first_set_winner": (day_offset + match_idx) % 2,
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
                        "avg_first_set_player_1_odds": 1.8,
                        "avg_first_set_player_2_odds": 2.1,
                        "avg_first_set_market_prob_player_1": 0.52,
                        "avg_first_set_market_prob_player_2": 0.45,
                        "avg_first_set_bookmaker_margin": 0.05,
                        "first_set_odds_bookmaker_count": 2,
                    }
                )
        return pd.DataFrame(rows)


class QuickEnsembleSmokeTest(unittest.TestCase):
    def test_grid_search_and_ensemble_on_synthetic_first_set(self):
        from pathlib import Path
        import tempfile

        from backend.src.app.ml.training.train_extra_markets_ensemble import (
            run_grid_search,
            run_stacking_then_voting,
        )

        frame = SyntheticMarketFrameHelper.first_set_frame()
        with tempfile.TemporaryDirectory() as tmp:
            reports_dir = Path(tmp) / "reports"
            models_dir = Path(tmp) / "models"
            search = run_grid_search(
                frame,
                "first_set_winner",
                dataset_path=Path("synthetic.csv"),
                reports_dir=reports_dir,
                models_dir=models_dir,
                quick=True,
            )
            self.assertEqual(len(search["algorithms"]), 5)
            self.assertGreaterEqual(len(search["top_algorithms_for_ensemble"]), 2)
            ensemble = run_stacking_then_voting(
                frame,
                "first_set_winner",
                search,
                dataset_path=Path("synthetic.csv"),
                reports_dir=reports_dir,
                models_dir=models_dir,
                quick=True,
            )
            self.assertIn("stacking", ensemble["ensembles"])
            self.assertIn("voting_soft", ensemble["ensembles"])
            self.assertIsNotNone(ensemble["ensembles"]["stacking"]["test_metrics"].get("roc_auc"))


if __name__ == "__main__":
    unittest.main()
