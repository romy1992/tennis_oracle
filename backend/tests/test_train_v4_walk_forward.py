"""Tests for the Fase 5 v4 walk-forward validation script (winner ensemble)."""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backend.src.app.ml.training.train_v4_walk_forward import (
    ENSEMBLE_MODEL_NAME,
    MATURE_CONFIG_OVERRIDES,
    MATURE_RESULTS_FILENAME,
    RESULTS_FILENAME,
    make_v4_voting_estimators_factory,
    run_v4_walk_forward,
)


def _synthetic_v3_dataset(n_days: int = 220, matches_per_day: int = 3) -> pd.DataFrame:
    # Stessa fixture di test_train_v4_ensemble.py, per coerenza tra i test Fase 3/4/5.
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


class MakeV4VotingEstimatorsFactoryTest(unittest.TestCase):
    def test_factory_builds_voting_classifier_with_three_base_estimators(self):
        from sklearn.ensemble import VotingClassifier

        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            factory = make_v4_voting_estimators_factory(tmp_dir)
            estimators = factory(42)

            self.assertEqual(set(estimators.keys()), {ENSEMBLE_MODEL_NAME})
            voting = estimators[ENSEMBLE_MODEL_NAME]
            self.assertIsInstance(voting, VotingClassifier)
            self.assertEqual(voting.voting, "soft")
            self.assertEqual(
                [name for name, _ in voting.estimators],
                ["logistic_regression", "xgboost", "hist_gradient_boosting"],
            )

    def test_factory_rebuilds_fresh_unfitted_estimators_each_call(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            factory = make_v4_voting_estimators_factory(tmp_dir)
            first = factory(42)[ENSEMBLE_MODEL_NAME]
            second = factory(42)[ENSEMBLE_MODEL_NAME]
            self.assertIsNot(first, second)


class RunV4WalkForwardEndToEndTest(unittest.TestCase):
    def test_quick_run_produces_report_with_expected_keys(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            processed_dir.mkdir(parents=True, exist_ok=True)

            dataframe = _synthetic_v3_dataset()
            dataset_path = processed_dir / "tennis_winner_dataset_with_odds_v3.csv"
            dataframe.to_csv(dataset_path, index=False)

            report = run_v4_walk_forward(
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                quick=True,
            )

            self.assertEqual(report["model_version"], "v3")
            self.assertEqual(report["ensemble_model_name"], ENSEMBLE_MODEL_NAME)
            self.assertTrue(report["quick_mode"])
            self.assertGreater(report["coverage"]["folds_planned"], 0)
            self.assertGreater(report["coverage"]["completed"], 0)
            self.assertEqual(report["coverage"]["errors"], 0)

            self.assertIn(ENSEMBLE_MODEL_NAME, report["aggregate_metrics"])
            ensemble_agg = report["aggregate_metrics"][ENSEMBLE_MODEL_NAME]
            self.assertIn("roc_auc", ensemble_agg)
            self.assertGreater(ensemble_agg["roc_auc"]["n"], 0)

            value_bet_agg = report["value_bet_aggregate_across_folds"]
            self.assertGreaterEqual(value_bet_agg["folds_with_bets"], 0)
            self.assertIn("roi_per_fold_stats", value_bet_agg)

            self.assertEqual(len(report["folds"]), report["coverage"]["fold_outcomes"])

            results_path = reports_dir / RESULTS_FILENAME
            self.assertTrue(results_path.exists())
            with results_path.open("r", encoding="utf-8") as results_file:
                persisted = json.load(results_file)
            self.assertEqual(persisted["ensemble_model_name"], ENSEMBLE_MODEL_NAME)

            # Non deve toccare i file ufficiali.
            self.assertFalse((reports_dir / "walk_forward" / "walk_forward_latest.json").exists())
            self.assertFalse((reports_dir / "model_registry.json").exists())
            self.assertFalse((reports_dir / "model_comparison.json").exists())

    def test_historical_comparison_is_none_when_no_official_report_exists(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            processed_dir.mkdir(parents=True, exist_ok=True)

            dataframe = _synthetic_v3_dataset()
            dataset_path = processed_dir / "tennis_winner_dataset_with_odds_v3.csv"
            dataframe.to_csv(dataset_path, index=False)

            report = run_v4_walk_forward(
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                quick=True,
            )
            self.assertIsNone(report["historical_lr_rf_comparison"])

    def test_quick_and_mature_are_mutually_exclusive(self):
        with self.assertRaises(ValueError):
            run_v4_walk_forward(quick=True, mature=True)


class RunV4WalkForwardMatureEndToEndTest(unittest.TestCase):
    def test_mature_run_uses_higher_initial_train_days_and_separate_report_file(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            processed_dir.mkdir(parents=True, exist_ok=True)

            # Dataset piu' lungo (600 giorni) per lasciare margine sopra
            # initial_train_days=1095 non e' necessario: verifichiamo solo che la
            # config venga applicata e che, con pochi giorni disponibili, i fold
            # risultino insufficienti (comportamento atteso e sicuro, nessun crash).
            dataframe = _synthetic_v3_dataset(n_days=220, matches_per_day=3)
            dataset_path = processed_dir / "tennis_winner_dataset_with_odds_v3.csv"
            dataframe.to_csv(dataset_path, index=False)

            report = run_v4_walk_forward(
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                mature=True,
            )

            self.assertTrue(report["mature_mode"])
            self.assertFalse(report["quick_mode"])
            self.assertEqual(report["phase"], "fase_5_2_walk_forward_mature_winner")
            self.assertEqual(
                report["config"]["initial_train_days"], MATURE_CONFIG_OVERRIDES["initial_train_days"]
            )
            # Con soli 220 giorni di dati sintetici e initial_train_days=1095, nessun
            # fold puo' essere generato: comportamento atteso, non un errore.
            self.assertEqual(report["coverage"]["folds_planned"], 0)

            mature_path = reports_dir / MATURE_RESULTS_FILENAME
            standard_path = reports_dir / RESULTS_FILENAME
            self.assertTrue(mature_path.exists())
            self.assertFalse(standard_path.exists(), "La Fase 5.2 non deve toccare il report della Fase 5 standard.")

            with mature_path.open("r", encoding="utf-8") as handle:
                persisted = json.load(handle)
            self.assertTrue(persisted["mature_mode"])

    def test_mature_run_does_not_overwrite_existing_standard_phase5_report(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            processed_dir.mkdir(parents=True, exist_ok=True)
            reports_dir.mkdir(parents=True, exist_ok=True)

            dataframe = _synthetic_v3_dataset()
            dataset_path = processed_dir / "tennis_winner_dataset_with_odds_v3.csv"
            dataframe.to_csv(dataset_path, index=False)

            # Simula un report Fase 5 standard gia' presente.
            standard_path = reports_dir / RESULTS_FILENAME
            sentinel_payload = {"phase": "fase_5_walk_forward_winner", "sentinel": True}
            with standard_path.open("w", encoding="utf-8") as handle:
                json.dump(sentinel_payload, handle)

            run_v4_walk_forward(processed_dir=processed_dir, reports_dir=reports_dir, mature=True)

            with standard_path.open("r", encoding="utf-8") as handle:
                unchanged = json.load(handle)
            self.assertEqual(unchanged, sentinel_payload)


if __name__ == "__main__":
    unittest.main()



