"""Tests for the ML-04 extension: v4 ensemble ROI segmentato per livello torneo."""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backend.src.app.ml.training.analyze_v4_segment_roi_by_level import (
    RESULTS_FILENAME,
    collect_v4_ensemble_segment_records,
    run_v4_segment_roi_analysis,
)
from backend.src.app.ml.training.walk_forward import WalkForwardConfig


# Livelli ciclati sulle righe: alcuni giorni non hanno match ATP trovato (livello
# mancante), per esercitare sia la segmentazione sia la nota dinamica sul
# segmento "Sconosciuto" (stessa relazione atp_match_found=0 <-> level NaN del
# dataset reale, riprodotta qui esplicitamente sui dati sintetici).
_LEVEL_CYCLE = ["G", "M", "A", "C", None]


def _synthetic_v3_dataset(n_days: int = 220, matches_per_day: int = 3) -> pd.DataFrame:
    # Stessa fixture di test_train_v4_walk_forward.py, con level/atp_match_found
    # variabili per riga invece di costanti, per popolare piu' segmenti.
    rows: list[dict] = []
    start = date(2023, 1, 1)
    for day_offset in range(n_days):
        day = start + timedelta(days=day_offset)
        for match_idx in range(matches_per_day):
            level = _LEVEL_CYCLE[(day_offset + match_idx) % len(_LEVEL_CYCLE)]
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
                    "atp_tourney_level": level,
                    "atp_round": "R32",
                    "atp_best_of": 3,
                    "atp_match_found": 0 if level is None else 1,
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


class CollectV4EnsembleSegmentRecordsTest(unittest.TestCase):
    def test_records_carry_level_field_and_coverage_matches_records(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            _write_dataset(processed_dir)

            config = WalkForwardConfig(
                initial_train_days=60, test_days=30, step_days=30, min_train_rows=20, min_test_rows=10
            )
            records, coverage = collect_v4_ensemble_segment_records(
                config, processed_dir=processed_dir, reports_dir=reports_dir
            )

            self.assertGreater(len(records), 0)
            self.assertEqual(coverage["total_records"], len(records))
            self.assertGreater(coverage["folds_completed"], 0)
            levels_seen = {item.level for item in records}
            # Deve comparire sia almeno un livello noto sia None (level mancante).
            self.assertTrue(levels_seen & {"G", "M", "A", "C"})
            self.assertIn(None, levels_seen)
            self.assertTrue(all(item.model_name == "voting_ensemble_v4" for item in records))


class RunV4SegmentRoiAnalysisEndToEndTest(unittest.TestCase):
    def test_quick_run_produces_report_segmented_by_level(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            _write_dataset(processed_dir)

            report = run_v4_segment_roi_analysis(
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                quick=True,
            )

            self.assertEqual(report["model_version"], "v3")
            self.assertEqual(report["ensemble_model_name"], "voting_ensemble_v4")
            self.assertEqual(report["segment_dimension"], "level")
            self.assertGreater(report["coverage"]["folds_completed"], 0)

            analysis = report["analysis"]
            self.assertGreater(analysis["predictions_total"], 0)
            segment_keys = {item["key"] for item in analysis["segments"]}
            self.assertIn("unknown", segment_keys)
            self.assertTrue(segment_keys & {"A", "C", "G", "M"})
            # Breakdown per fold attivo di default.
            self.assertGreater(len(analysis["by_fold"]), 0)

            # Nota dinamica sulla percentuale di livello mancante presente.
            self.assertTrue(
                any("Sconosciuto" in note and "atp_match_found=0" in note for note in report["notes"])
            )

            results_path = reports_dir / RESULTS_FILENAME
            self.assertTrue(results_path.exists())
            with results_path.open("r", encoding="utf-8") as results_file:
                persisted = json.load(results_file)
            self.assertEqual(persisted["segment_dimension"], "level")

            # Non deve mai toccare i file ufficiali/produzione.
            self.assertFalse((reports_dir / "model_registry.json").exists())
            self.assertFalse((reports_dir / "model_comparison.json").exists())
            self.assertFalse((reports_dir / "walk_forward" / "walk_forward_latest.json").exists())

    def test_quick_and_mature_are_mutually_exclusive(self):
        with self.assertRaises(ValueError):
            run_v4_segment_roi_analysis(quick=True, mature=True)

    def test_invalid_segment_dimension_raises(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            _write_dataset(processed_dir)
            with self.assertRaises(ValueError):
                run_v4_segment_roi_analysis(
                    processed_dir=processed_dir,
                    reports_dir=reports_dir,
                    segment_dimension="not_a_real_dimension",  # type: ignore[arg-type]
                    quick=True,
                )

    def test_other_segment_dimension_still_works(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            _write_dataset(processed_dir)

            report = run_v4_segment_roi_analysis(
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                segment_dimension="surface",
                quick=True,
            )
            self.assertEqual(report["segment_dimension"], "surface")
            segment_keys = {item["key"] for item in report["analysis"]["segments"]}
            self.assertTrue(segment_keys & {"Hard", "Clay"})


if __name__ == "__main__":
    unittest.main()

