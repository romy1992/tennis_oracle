import unittest
from datetime import date

from backend.src.app.ml.datasets.dataset_builder import (
    DEFAULT_ELO_VALUE,
    LegacyMatchRow,
    clean_dataset_dataframe,
    legacy_match_rows_to_dataframe_v2,
)
from backend.src.app.ml.datasets.elo_builder import (
    EloTracker,
    INITIAL_ELO,
    K_FACTOR,
    expected_score,
    update_elo,
)


class EloBuilderTest(unittest.TestCase):
    def test_update_elo_after_win_and_loss(self):
        winner_before = 1600.0
        loser_before = 1400.0
        winner_after, loser_after = update_elo(winner_before, loser_before, k_factor=K_FACTOR)

        self.assertGreater(winner_after, winner_before)
        self.assertLess(loser_after, loser_before)
        self.assertAlmostEqual(
            winner_after - winner_before,
            loser_before - loser_after,
            places=6,
        )

    def test_expected_score_is_symmetric(self):
        self.assertAlmostEqual(expected_score(1500, 1500), 0.5)
        self.assertGreater(expected_score(1600, 1400), 0.5)

    def test_same_day_matches_do_not_use_current_result(self):
        dataframe = legacy_match_rows_to_dataframe_v2(
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
            ]
        )
        cleaned = clean_dataset_dataframe(dataframe)

        self.assertEqual(cleaned.loc[0, "player_1_elo"], DEFAULT_ELO_VALUE)
        self.assertEqual(cleaned.loc[1, "player_1_elo"], DEFAULT_ELO_VALUE)

    def test_elo_updates_after_prior_day_result(self):
        tracker = EloTracker()
        tracker.record_match(1, 2, "Hard", player_1_won=True)
        features = tracker.pre_match_features(1, 2, "Hard")

        self.assertGreater(features.player_1_elo, INITIAL_ELO)
        self.assertLess(features.player_2_elo, INITIAL_ELO)


if __name__ == "__main__":
    unittest.main()
