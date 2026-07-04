import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from backend.src.app.ml.datasets.dataset_builder import MISSING_RANK_VALUE
from backend.src.app.ml.datasets.ranking_history import (
    HistoricalRankingLookup,
    build_player_key_to_atp_id_mapping,
    load_atp_rankings,
    ranking_date_to_date,
)


class RankingHistoryTest(unittest.TestCase):
    def test_ranking_date_is_parsed(self):
        self.assertEqual(ranking_date_to_date(20240101), date(2024, 1, 1))

    def test_lookup_uses_latest_ranking_on_or_before_match_date(self):
        rankings = pd.DataFrame(
            [
                {"ranking_date": 20240101, "rank": 10, "player": 100, "points": 5000},
                {"ranking_date": 20240108, "rank": 8, "player": 100, "points": 5200},
                {"ranking_date": 20240115, "rank": 5, "player": 100, "points": 5400},
            ]
        )
        lookup = HistoricalRankingLookup(rankings, {1: 100})

        rank_before, points_before = lookup.lookup_player_key(1, date(2024, 1, 7))
        rank_on, points_on = lookup.lookup_player_key(1, date(2024, 1, 8))
        rank_after, points_after = lookup.lookup_player_key(1, date(2024, 1, 20))

        self.assertEqual((rank_before, points_before), (10, 5000))
        self.assertEqual((rank_on, points_on), (8, 5200))
        self.assertEqual((rank_after, points_after), (5, 5400))

    def test_unmapped_player_gets_missing_rank(self):
        lookup = HistoricalRankingLookup(pd.DataFrame(), {})
        rank, points = lookup.lookup_player_key(999, date(2024, 1, 1))
        self.assertEqual(rank, MISSING_RANK_VALUE)
        self.assertEqual(points, 0)

    def test_player_mapping_is_built_from_match_mapping(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mapping_path = temp_path / "match_mapping.csv"
            base_path = temp_path / "base.csv"
            pd.DataFrame(
                [
                    {
                        "match_id": 1,
                        "match_date": "2024-01-01",
                        "player_1_id": 11,
                        "player_2_id": 22,
                    }
                ]
            ).to_csv(base_path, index=False)
            pd.DataFrame(
                [
                    {
                        "match_id": 1,
                        "match_date": "2024-01-01",
                        "player_1_atp_id": 100,
                        "player_2_atp_id": 200,
                    }
                ]
            ).to_csv(mapping_path, index=False)

            mapping = build_player_key_to_atp_id_mapping(mapping_path, base_path)
            self.assertEqual(mapping[11], 100)
            self.assertEqual(mapping[22], 200)

    def test_load_atp_rankings_reads_glob(self):
        with TemporaryDirectory() as temp_dir:
            rankings_dir = Path(temp_dir)
            pd.DataFrame(
                [{"ranking_date": 20200106, "rank": 1, "player": 104745, "points": 9985}]
            ).to_csv(rankings_dir / "atp_rankings_20s.csv", index=False)

            loaded = load_atp_rankings(rankings_dir)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(int(loaded.iloc[0]["player"]), 104745)


if __name__ == "__main__":
    unittest.main()
