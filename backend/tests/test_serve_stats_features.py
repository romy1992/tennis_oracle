"""Tests for app.ml.datasets.serve_stats_features (feature esplorative di
dominanza al servizio, usate solo da train_v4_serve_stats_experiment.py).

Nessun modello viene allenato qui: solo estrazione/aggregazione dati (corpus,
indice rolling anti-leakage, crosswalk id interno -> atp_id, arricchimento
dataframe finale).
"""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from backend.src.app.ml.datasets.serve_stats_features import (
    EXTRA_FEATURE_COLUMNS,
    METRIC_NAMES,
    PlayerServeStatIndex,
    add_serve_stat_features,
    build_internal_id_to_atp_id_crosswalk,
    load_serve_stats_corpus,
)


def _row(tourney_date: int, winner_id: int, loser_id: int, **overrides) -> dict:
    base = {
        "tourney_date": tourney_date,
        "winner_id": winner_id,
        "loser_id": loser_id,
        "w_ace": 5, "w_df": 2, "w_svpt": 80, "w_1stIn": 50, "w_1stWon": 40,
        "w_2ndWon": 15, "w_SvGms": 10, "w_bpSaved": 3, "w_bpFaced": 5,
        "l_ace": 3, "l_df": 4, "l_svpt": 75, "l_1stIn": 45, "l_1stWon": 30,
        "l_2ndWon": 10, "l_SvGms": 9, "l_bpSaved": 2, "l_bpFaced": 6,
    }
    base.update(overrides)
    return base


class LoadServeStatsCorpusTest(unittest.TestCase):
    def test_corpus_has_one_row_per_player_per_match_with_correct_metrics(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            atp_dir = Path(tmp_dir)
            frame = pd.DataFrame([_row(20200101, winner_id=100, loser_id=200)])
            frame.to_csv(atp_dir / "atp_matches_2020.csv", index=False)

            corpus = load_serve_stats_corpus(atp_dir, year_start=2020, year_end=2020)

            self.assertEqual(len(corpus), 2)
            winner_row = corpus[corpus["atp_id"] == 100].iloc[0]
            loser_row = corpus[corpus["atp_id"] == 200].iloc[0]

            self.assertAlmostEqual(winner_row["serve_pts_won_pct"], 55 / 80)
            self.assertAlmostEqual(winner_row["bp_saved_pct"], 3 / 5)
            self.assertAlmostEqual(winner_row["ace_rate"], 5 / 80)

            self.assertAlmostEqual(loser_row["serve_pts_won_pct"], 40 / 75)
            self.assertAlmostEqual(loser_row["bp_saved_pct"], 2 / 6)
            self.assertAlmostEqual(loser_row["ace_rate"], 3 / 75)

    def test_rows_with_missing_stat_values_are_dropped(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            atp_dir = Path(tmp_dir)
            complete = _row(20200101, winner_id=100, loser_id=200)
            incomplete = _row(20200102, winner_id=101, loser_id=201, w_ace=np.nan)
            frame = pd.DataFrame([complete, incomplete])
            frame.to_csv(atp_dir / "atp_matches_2020.csv", index=False)

            corpus = load_serve_stats_corpus(atp_dir, year_start=2020, year_end=2020)

            # Solo la riga "complete" contribuisce (2 righe: winner + loser).
            self.assertEqual(len(corpus), 2)
            self.assertNotIn(101, set(corpus["atp_id"]))
            self.assertNotIn(201, set(corpus["atp_id"]))

    def test_missing_required_column_skips_file_without_raising(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            atp_dir = Path(tmp_dir)
            frame = pd.DataFrame([_row(20200101, winner_id=100, loser_id=200)]).drop(columns=["w_ace"])
            frame.to_csv(atp_dir / "atp_matches_2020.csv", index=False)

            corpus = load_serve_stats_corpus(atp_dir, year_start=2020, year_end=2020)

            self.assertTrue(corpus.empty)

    def test_reads_both_tour_and_qual_chall_files_for_same_year(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            atp_dir = Path(tmp_dir)
            tour = pd.DataFrame([_row(20200101, winner_id=100, loser_id=200)])
            qual = pd.DataFrame([_row(20200103, winner_id=300, loser_id=400)])
            tour.to_csv(atp_dir / "atp_matches_2020.csv", index=False)
            qual.to_csv(atp_dir / "atp_matches_qual_chall_2020.csv", index=False)

            corpus = load_serve_stats_corpus(atp_dir, year_start=2020, year_end=2020)

            self.assertEqual(set(corpus["atp_id"]), {100, 200, 300, 400})

    def test_futures_files_are_never_read(self):
        # SERVE_STAT_SOURCE_KINDS non include "atp_matches_futures": confermato
        # empiricamente 0% di copertura statistiche di servizio su quel livello.
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            atp_dir = Path(tmp_dir)
            futures = pd.DataFrame([_row(20200101, winner_id=999, loser_id=998)])
            futures.to_csv(atp_dir / "atp_matches_futures_2020.csv", index=False)

            corpus = load_serve_stats_corpus(atp_dir, year_start=2020, year_end=2020)

            self.assertTrue(corpus.empty)


class PlayerServeStatIndexTest(unittest.TestCase):
    def test_unknown_player_returns_all_none(self):
        corpus = pd.DataFrame(columns=["atp_id", "date", *METRIC_NAMES])
        index = PlayerServeStatIndex(corpus, window=10)
        result = index.rolling_averages(999, date(2023, 1, 1))
        self.assertEqual(result, {metric: None for metric in METRIC_NAMES})

    def test_rolling_average_uses_only_matches_strictly_before_date_anti_leakage(self):
        # 3 partite: 2 prima della data target, 1 dopo (deve essere ignorata:
        # stesso principio anti-leakage di calculate_win_rate_last_n).
        corpus = pd.DataFrame(
            {
                "atp_id": [1, 1, 1],
                "date": pd.to_datetime(["2023-01-01", "2023-01-05", "2023-01-10"]),
                "serve_pts_won_pct": [0.5, 0.7, 0.9],
                "bp_saved_pct": [0.5, 0.5, 0.5],
                "ace_rate": [0.1, 0.1, 0.1],
            }
        )
        index = PlayerServeStatIndex(corpus, window=10)

        # before_date = 2023-01-06: include solo le partite del 01-01 e 01-05
        # (media 0.6), NON quella del 01-10 (sarebbe leakage).
        result = index.rolling_averages(1, "2023-01-06")
        self.assertAlmostEqual(result["serve_pts_won_pct"], 0.6)

        # before_date = 2023-01-01 (uguale alla prima data storica, side="left"):
        # nessuna partita strettamente precedente -> None.
        result_none = index.rolling_averages(1, "2023-01-01")
        self.assertEqual(result_none["serve_pts_won_pct"], None)

    def test_rolling_average_respects_window_size(self):
        dates = pd.date_range("2023-01-01", periods=15, freq="D")
        values = [float(i) / 100 for i in range(15)]  # 0.00, 0.01, ..., 0.14
        corpus = pd.DataFrame(
            {
                "atp_id": [1] * 15,
                "date": dates,
                "serve_pts_won_pct": values,
                "bp_saved_pct": values,
                "ace_rate": values,
            }
        )
        index = PlayerServeStatIndex(corpus, window=5)

        # before_date successiva a tutte e 15: la finestra prende solo le
        # ULTIME 5 (indici 10..14 -> valori 0.10..0.14).
        result = index.rolling_averages(1, "2023-02-01")
        self.assertAlmostEqual(result["serve_pts_won_pct"], sum(values[10:15]) / 5)


class BuildInternalIdToAtpIdCrosswalkTest(unittest.TestCase):
    def test_only_rows_with_atp_match_found_contribute(self):
        dataframe = pd.DataFrame(
            {
                "player_1_id": [1, 2, 3],
                "player_2_id": [4, 5, 6],
                "player_1_atp_id": [100, 200, np.nan],
                "player_2_atp_id": [400, np.nan, 600],
                "atp_match_found": [1, 1, 0],
            }
        )
        crosswalk = build_internal_id_to_atp_id_crosswalk(dataframe)
        self.assertEqual(crosswalk, {1: 100, 2: 200, 4: 400})
        # Riga con atp_match_found=0 non contribuisce, anche se i valori sono popolati.
        self.assertNotIn(3, crosswalk)
        self.assertNotIn(6, crosswalk)

    def test_player_matched_in_any_row_contributes_even_if_current_row_unmatched(self):
        # Stesso principio validato nell'analisi di densita' per-giocatore: un
        # giocatore con ALMENO una riga storica risolta contribuisce al crosswalk.
        dataframe = pd.DataFrame(
            {
                "player_1_id": [1, 1],
                "player_2_id": [4, 5],
                "player_1_atp_id": [100, 100],
                "player_2_atp_id": [400, np.nan],
                "atp_match_found": [1, 0],
            }
        )
        crosswalk = build_internal_id_to_atp_id_crosswalk(dataframe)
        self.assertEqual(crosswalk[1], 100)


class AddServeStatFeaturesTest(unittest.TestCase):
    def test_adds_expected_columns_without_mutating_input(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            atp_dir = Path(tmp_dir)
            history = pd.DataFrame(
                [
                    _row(20220101, winner_id=100, loser_id=200),
                    _row(20220201, winner_id=100, loser_id=300),
                ]
            )
            history.to_csv(atp_dir / "atp_matches_2022.csv", index=False)

            dataframe = pd.DataFrame(
                {
                    "match_date": ["2023-01-01"],
                    "player_1_id": [1],
                    "player_2_id": [2],
                    "player_1_atp_id": [100],
                    "player_2_atp_id": [300],
                    "atp_match_found": [1],
                }
            )
            original_columns = set(dataframe.columns)

            result = add_serve_stat_features(dataframe, atp_dir, window=10)

            # L'originale non viene mutato.
            self.assertEqual(set(dataframe.columns), original_columns)
            for column in EXTRA_FEATURE_COLUMNS:
                self.assertIn(column, result.columns)

            # player_1 (atp_id=100) ha vinto entrambe le partite storiche;
            # player_2 (atp_id=300) ha perso una partita (2022-02-01): entrambi
            # hanno storia sufficiente prima del 2023-01-01 per un valore non-None.
            self.assertIsNotNone(result.loc[0, "player_1_serve_pts_won_pct_last10"])
            self.assertIsNotNone(result.loc[0, "player_2_serve_pts_won_pct_last10"])
            self.assertAlmostEqual(
                result.loc[0, "serve_pts_won_pct_diff"],
                result.loc[0, "player_1_serve_pts_won_pct_last10"]
                - result.loc[0, "player_2_serve_pts_won_pct_last10"],
            )

    def test_unmatched_players_yield_none_features(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            atp_dir = Path(tmp_dir)
            dataframe = pd.DataFrame(
                {
                    "match_date": ["2023-01-01"],
                    "player_1_id": [1],
                    "player_2_id": [2],
                    "player_1_atp_id": [np.nan],
                    "player_2_atp_id": [np.nan],
                    "atp_match_found": [0],
                }
            )
            result = add_serve_stat_features(dataframe, atp_dir, window=10)
            self.assertIsNone(result.loc[0, "player_1_serve_pts_won_pct_last10"])
            self.assertIsNone(result.loc[0, "player_2_serve_pts_won_pct_last10"])


if __name__ == "__main__":
    unittest.main()


