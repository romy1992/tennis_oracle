import unittest
from datetime import date

import pandas as pd

from backend.src.app.ml.datasets.dataset_builder import (
    DATASET_COLUMNS,
    DEFAULT_ELO_VALUE,
    DEFAULT_WIN_RATE_VALUE,
    LegacyMatchRow,
    MISSING_DAYS_SINCE_LAST_MATCH,
    MISSING_RANK_VALUE,
    clean_dataset_dataframe,
    legacy_match_rows_to_dataframe,
    summarize_dataset,
)
from backend.src.app.ml.datasets.atp_singles_enrichment import (
    set_score_from_atp_score,
    short_player_name,
)


class DatasetBuilderTest(unittest.TestCase):
    def test_atp_score_is_converted_to_set_score(self):
        self.assertEqual(set_score_from_atp_score("7-6(5) 6-4"), (2, 0))
        self.assertEqual(set_score_from_atp_score("3-6 6-4 6-4"), (2, 1))
        self.assertEqual(set_score_from_atp_score("5-7 6-1 0-0 RET"), (1, 1))

    def test_atp_name_is_normalized_to_fixture_short_name(self):
        self.assertEqual(short_player_name("Grigor Dimitrov"), "g dimitrov")
        self.assertEqual(short_player_name("G. Dimitrov"), "g dimitrov")

    def test_clean_dataset_imputes_missing_values(self):
        dataframe = pd.DataFrame(
            [
                {
                    "match_id": 1,
                    "feature_date": date(2024, 1, 1),
                    "surface": None,
                    "player_1_id": 10,
                    "player_2_id": 20,
                    "player_1_rank": None,
                    "player_2_rank": 25,
                    "player_1_elo": None,
                    "player_2_elo": None,
                    "player_1_surface_elo": None,
                    "player_2_surface_elo": None,
                    "target_player_1_win": 1,
                }
            ]
        )

        cleaned = clean_dataset_dataframe(dataframe)

        self.assertEqual(list(cleaned.columns), DATASET_COLUMNS)
        self.assertEqual(int(cleaned.isna().sum().sum()), 0)
        self.assertEqual(cleaned.loc[0, "surface"], "unknown")
        self.assertEqual(cleaned.loc[0, "player_1_rank"], MISSING_RANK_VALUE)
        self.assertEqual(cleaned.loc[0, "rank_diff"], MISSING_RANK_VALUE - 25)
        self.assertEqual(cleaned.loc[0, "player_1_elo"], DEFAULT_ELO_VALUE)
        self.assertEqual(cleaned.loc[0, "elo_diff"], 0.0)
        self.assertEqual(
            cleaned.loc[0, "player_1_last_5_win_rate"],
            DEFAULT_WIN_RATE_VALUE,
        )
        self.assertEqual(cleaned.loc[0, "h2h_player_1_wins"], 0)
        self.assertEqual(
            cleaned.loc[0, "player_1_days_since_last_match"],
            MISSING_DAYS_SINCE_LAST_MATCH,
        )

    def test_summarize_dataset_reports_target_and_date_range(self):
        dataframe = pd.DataFrame(
            [
                {"match_date": date(2024, 1, 1), "target_player_1_win": 1},
                {"match_date": date(2024, 1, 2), "target_player_1_win": 0},
            ]
        )

        summary = summarize_dataset(dataframe)

        self.assertEqual(summary.total_rows, 2)
        self.assertEqual(summary.target_percentages, {1: 50.0, 0: 50.0})
        self.assertEqual(summary.date_min, date(2024, 1, 1))
        self.assertEqual(summary.date_max, date(2024, 1, 2))

    def test_legacy_rows_do_not_use_same_day_results_as_history(self):
        dataframe = legacy_match_rows_to_dataframe(
            [
                LegacyMatchRow(
                    match_id=1,
                    match_date=date(2024, 1, 1),
                    surface="Hard",
                    player_1_id=1,
                    player_2_id=2,
                    target_player_1_win=1,
                ),
                LegacyMatchRow(
                    match_id=2,
                    match_date=date(2024, 1, 1),
                    surface="Hard",
                    player_1_id=1,
                    player_2_id=3,
                    target_player_1_win=0,
                ),
                LegacyMatchRow(
                    match_id=3,
                    match_date=date(2024, 1, 2),
                    surface="Hard",
                    player_1_id=1,
                    player_2_id=4,
                    target_player_1_win=1,
                ),
            ]
        )

        cleaned = clean_dataset_dataframe(dataframe)

        self.assertEqual(
            cleaned.loc[0, "player_1_last_5_win_rate"],
            DEFAULT_WIN_RATE_VALUE,
        )
        self.assertEqual(
            cleaned.loc[1, "player_1_last_5_win_rate"],
            DEFAULT_WIN_RATE_VALUE,
        )
        self.assertEqual(cleaned.loc[2, "player_1_last_5_win_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
