"""Tests for the serve-stats feature experiment (train_v4_serve_stats_experiment.py).

Dataset e storia ATP interamente sintetici (nessun DB, nessun file di produzione
toccato): stesso pattern di test_analyze_v4_segment_roi_by_level.py, esteso con
le colonne necessarie all'arricchimento serve-stats (player_*_id, player_*_atp_id,
atp_match_found) e con CSV ATP storici sintetici in una cartella temporanea.
"""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backend.src.app.ml.datasets.serve_stats_features import (
    EXTRA_FEATURE_COLUMNS,
    add_serve_stat_features,
)
from backend.src.app.ml.training.train_v4_serve_stats_experiment import (
    ENSEMBLE_MODEL_NAME,
    EXPERIMENT_MODEL_NAMES,
    RESULTS_FILENAME,
    STACKING_MODEL_NAME,
    excluded_feature_columns_experiment,
    run_serve_stats_experiment,
    selected_feature_columns_experiment,
)


def _synthetic_v3_dataset(n_days: int = 220, matches_per_day: int = 3, n_players: int = 12) -> pd.DataFrame:
    rows: list[dict] = []
    start = date(2023, 1, 1)
    for day_offset in range(n_days):
        day = start + timedelta(days=day_offset)
        for match_idx in range(matches_per_day):
            p1 = (day_offset + match_idx) % n_players
            p2 = (p1 + 1 + match_idx) % n_players
            rows.append(
                {
                    "match_id": day_offset * matches_per_day + match_idx,
                    "match_date": day.isoformat(),
                    "target_player_1_win": (day_offset + match_idx) % 2,
                    "surface": "Hard" if day_offset % 2 == 0 else "Clay",
                    "player_1_id": p1,
                    "player_2_id": p2,
                    "player_1_atp_id": 1000 + p1,
                    "player_2_atp_id": 1000 + p2,
                    "atp_match_found": 1,
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


def _write_dataset(processed_dir: Path) -> Path:
    processed_dir.mkdir(parents=True, exist_ok=True)
    dataframe = _synthetic_v3_dataset()
    dataset_path = processed_dir / "tennis_winner_dataset_with_odds_v3.csv"
    dataframe.to_csv(dataset_path, index=False)
    return dataset_path


def _write_atp_history(atp_data_dir: Path, n_players: int = 12) -> None:
    # Storia interamente precedente (2021, ~300 giorni) al dataset di test
    # (2023+): ogni giocatore ha decine di partite storiche disponibili prima
    # di qualunque match_date del dataset, cosi' le medie rolling sono sempre
    # calcolabili (nessun problema di finestra iniziale vuota).
    atp_data_dir.mkdir(parents=True, exist_ok=True)
    base_date = date(2021, 1, 1)
    rows = []
    for i in range(400):
        winner = i % n_players
        loser = (winner + 1) % n_players
        match_date = base_date + timedelta(days=i % 300)
        rows.append(
            {
                "tourney_date": int(match_date.strftime("%Y%m%d")),
                "winner_id": 1000 + winner,
                "loser_id": 1000 + loser,
                "w_ace": 5, "w_df": 2, "w_svpt": 80, "w_1stIn": 50, "w_1stWon": 40,
                "w_2ndWon": 15, "w_SvGms": 10, "w_bpSaved": 3, "w_bpFaced": 5,
                "l_ace": 3, "l_df": 4, "l_svpt": 75, "l_1stIn": 45, "l_1stWon": 30,
                "l_2ndWon": 10, "l_SvGms": 9, "l_bpSaved": 2, "l_bpFaced": 6,
            }
        )
    pd.DataFrame(rows).to_csv(atp_data_dir / "atp_matches_2021.csv", index=False)


class SelectedFeatureColumnsExperimentTest(unittest.TestCase):
    def test_includes_v3_columns_plus_serve_stats_extras(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            atp_dir = Path(tmp_dir) / "atp"
            dataset_path = _write_dataset(processed_dir)
            _write_atp_history(atp_dir)

            dataframe = pd.read_csv(dataset_path)
            enriched = add_serve_stat_features(dataframe, atp_dir)

            features = selected_feature_columns_experiment(enriched)
            self.assertIn("elo_diff", features)  # colonna v3 originale
            for extra in EXTRA_FEATURE_COLUMNS:
                self.assertIn(extra, features)

    def test_excluded_columns_never_overlap_selected_features(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            atp_dir = Path(tmp_dir) / "atp"
            dataset_path = _write_dataset(processed_dir)
            _write_atp_history(atp_dir)

            dataframe = pd.read_csv(dataset_path)
            enriched = add_serve_stat_features(dataframe, atp_dir)

            selected = selected_feature_columns_experiment(enriched)
            excluded = excluded_feature_columns_experiment(enriched, selected)
            self.assertFalse(set(selected) & set(excluded))
            self.assertIn("match_date", excluded)  # sempre esclusa (leakage/id)


class RunServeStatsExperimentEndToEndTest(unittest.TestCase):
    def test_quick_run_produces_report_with_all_models_and_baseline_comparison(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            atp_dir = Path(tmp_dir) / "atp"
            _write_dataset(processed_dir)
            _write_atp_history(atp_dir)

            report = run_serve_stats_experiment(
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                atp_data_dir=atp_dir,
                quick=True,
            )

            self.assertEqual(report["model_version_base"], "v3")
            self.assertEqual(report["extra_feature_columns"], EXTRA_FEATURE_COLUMNS)
            self.assertGreater(report["coverage"]["completed"], 0)

            for model_name in EXPERIMENT_MODEL_NAMES:
                self.assertIn(model_name, report["aggregate_metrics"])
                self.assertIn(model_name, report["value_bet_aggregate_across_folds"])
            self.assertEqual(len(EXPERIMENT_MODEL_NAMES), 4)
            self.assertIn(ENSEMBLE_MODEL_NAME, EXPERIMENT_MODEL_NAMES)
            self.assertIn(STACKING_MODEL_NAME, EXPERIMENT_MODEL_NAMES)

            self.assertIn("baseline_v3_no_serve_stats", report)
            self.assertIn(
                "logistic_regression", report["baseline_v3_no_serve_stats"]["aggregate_metrics"]
            )

            # Storia ATP sintetica precede tutte le match_date: le feature
            # serve-stats devono comparire nel feature-set finale.
            self.assertGreater(
                len(report["coverage"]["serve_stats_features_present_in_final_set"]), 0
            )

            results_path = reports_dir / RESULTS_FILENAME
            self.assertTrue(results_path.exists())
            with results_path.open("r", encoding="utf-8") as results_file:
                persisted = json.load(results_file)
            self.assertEqual(persisted["model_version_base"], "v3")

            # Non deve mai toccare i file ufficiali/produzione.
            self.assertFalse((reports_dir / "model_registry.json").exists())
            self.assertFalse((reports_dir / "model_comparison.json").exists())
            self.assertFalse((reports_dir / "v4_ensemble_results.json").exists())
            self.assertFalse((reports_dir / "v4_walk_forward_results.json").exists())

    def test_historical_ensemble_comparison_is_none_when_no_official_report_exists(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            atp_dir = Path(tmp_dir) / "atp"
            _write_dataset(processed_dir)
            _write_atp_history(atp_dir)

            report = run_serve_stats_experiment(
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                atp_data_dir=atp_dir,
                quick=True,
            )
            self.assertIsNone(report["historical_v4_ensemble_walk_forward_no_serve_stats"])


if __name__ == "__main__":
    unittest.main()



