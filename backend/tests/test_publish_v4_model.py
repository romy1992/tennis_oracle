"""Tests for the Fase 6 official v4 publication script (voting ensemble)."""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backend.src.app.ml.training.publish_v4_model import (
    MODEL_NAME,
    MODEL_VERSION,
    publish_v4_model,
)


def _synthetic_v3_dataset(n_days: int = 220, matches_per_day: int = 3) -> pd.DataFrame:
    # Stessa fixture di test_train_v4_ensemble.py, per coerenza tra gli script v4.
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


class PublishV4ModelEndToEndTest(unittest.TestCase):
    def test_publish_writes_pkl_and_metrics_in_official_format(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            processed_dir = Path(tmp_dir) / "processed"
            reports_dir = Path(tmp_dir) / "reports"
            models_dir = Path(tmp_dir) / "models" / "v4"
            registry_path = reports_dir / "model_registry.json"
            processed_dir.mkdir(parents=True, exist_ok=True)

            dataframe = _synthetic_v3_dataset()
            dataset_path = processed_dir / "tennis_winner_dataset_with_odds_v3.csv"
            dataframe.to_csv(dataset_path, index=False)

            result = publish_v4_model(
                processed_dir=processed_dir,
                models_dir=models_dir,
                reports_dir=reports_dir,
                registry_path=registry_path,
            )

            self.assertEqual(result.model_version, MODEL_VERSION)
            self.assertIn(MODEL_NAME, result.model_paths)
            model_path = result.model_paths[MODEL_NAME]
            self.assertTrue(model_path.exists())

            # Formato atteso da predictor._load_model_artifact: dict con "pipeline"
            # e "feature_columns" (compatibile 1:1 con v1/v2/v3).
            import pickle

            with model_path.open("rb") as handle:
                artifact = pickle.load(handle)
            self.assertIn("pipeline", artifact)
            self.assertIn("feature_columns", artifact)
            self.assertTrue(hasattr(artifact["pipeline"], "predict_proba"))

            # Metriche nello stesso schema di baseline_v3_metrics.json.
            self.assertTrue(result.metrics_path.exists())
            with result.metrics_path.open("r", encoding="utf-8") as handle:
                persisted = json.load(handle)
            self.assertEqual(persisted["model_version"], MODEL_VERSION)
            self.assertIn(MODEL_NAME, persisted["models"])
            self.assertIn("roc_auc", persisted["models"][MODEL_NAME])
            self.assertIn("value_bet_overall", persisted["models"][MODEL_NAME])
            self.assertIn("market_benchmark", persisted)

            # model_comparison.json e model_registry.json aggiornati (riusa
            # write_model_comparison/update_model_registry_entry di train_baseline).
            self.assertTrue((reports_dir / "model_comparison.json").exists())
            self.assertTrue(registry_path.exists())
            with registry_path.open("r", encoding="utf-8") as handle:
                registry = json.load(handle)
            registry_ids = {entry.get("id") for entry in registry.get("versions", [])}
            self.assertIn("v4", registry_ids)


if __name__ == "__main__":
    unittest.main()



