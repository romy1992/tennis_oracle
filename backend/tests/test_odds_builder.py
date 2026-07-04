import unittest
from datetime import date

import pandas as pd

from backend.src.app.ml.datasets.odds_builder import (
    FixtureOddsRecord,
    aggregate_match_odds,
    attach_odds_to_dataset,
    average_match_winner_odds_from_record,
    bookmaker_margin,
    decimal_odd,
    implied_probability,
    match_winner_rows_from_record,
    no_vig_market_probabilities,
    profit_for_unit_stake,
)


class OddsBuilderTest(unittest.TestCase):
    def test_decimal_odds_are_converted_to_implied_probability(self):
        self.assertEqual(decimal_odd("2,50"), 2.5)
        self.assertIsNone(decimal_odd("1.00"))
        self.assertAlmostEqual(implied_probability(2.0), 0.5)

    def test_no_vig_probabilities_are_normalized(self):
        player_1, player_2 = no_vig_market_probabilities(2.0, 2.0)

        self.assertAlmostEqual(player_1, 0.5)
        self.assertAlmostEqual(player_2, 0.5)
        self.assertAlmostEqual(player_1 + player_2, 1.0)

    def test_bookmaker_margin_is_calculated(self):
        self.assertAlmostEqual(bookmaker_margin(1.8, 2.2), (1 / 1.8) + (1 / 2.2) - 1)

    def test_profit_for_won_and_lost_bets(self):
        self.assertAlmostEqual(profit_for_unit_stake(2.4, won=True), 1.4)
        self.assertEqual(profit_for_unit_stake(2.4, won=False), -1.0)

    def test_match_winner_parser_outputs_one_row_per_bookmaker(self):
        record = FixtureOddsRecord(
            match_id=100,
            match_date=date(2024, 1, 1),
            player_1_id=1,
            player_2_id=2,
            player_1_name="Player A",
            player_2_name="Player B",
            odds={
                "Home/Away": {
                    "Home": {"Book A": "2.00", "Book B": "1.80", "Bad": "1.00"},
                    "Away": {"Book A": "1.90", "Book B": "2.10", "Bad": "3.00"},
                }
            },
            event_live=0,
        )

        rows = match_winner_rows_from_record(record)

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["bookmaker"] for row in rows}, {"Book A", "Book B"})

    def test_average_match_winner_odds_extracts_player_one_and_two(self):
        record = FixtureOddsRecord(
            match_id=100,
            match_date=date(2024, 1, 1),
            player_1_id=1,
            player_2_id=2,
            player_1_name="Player A",
            player_2_name="Player B",
            odds={
                "Home/Away": {
                    "Home": {"Book A": "2.00", "Book B": "2.20"},
                    "Away": {"Book A": "1.80", "Book B": "1.90"},
                }
            },
            event_live=0,
        )

        average = average_match_winner_odds_from_record(record)

        self.assertIsNotNone(average)
        self.assertAlmostEqual(average.avg_player_1_odds, 2.1)
        self.assertAlmostEqual(average.avg_player_2_odds, 1.85)
        self.assertEqual(average.odds_bookmaker_count, 2)

    def test_average_match_winner_odds_accepts_event_key_wrapped_payload(self):
        record = FixtureOddsRecord(
            match_id=100,
            match_date=date(2024, 1, 1),
            player_1_id=1,
            player_2_id=2,
            player_1_name="Player A",
            player_2_name="Player B",
            odds={
                "100": {
                    "Home/Away": {
                        "Home": {"Book A": "1.70", "Book B": "1.80"},
                        "Away": {"Book A": "2.10", "Book B": "2.20"},
                    }
                }
            },
            event_live=0,
        )

        average = average_match_winner_odds_from_record(record)

        self.assertIsNotNone(average)
        self.assertAlmostEqual(average.avg_player_1_odds, 1.75)
        self.assertAlmostEqual(average.avg_player_2_odds, 2.15)
        self.assertEqual(average.odds_bookmaker_count, 2)

    def test_multi_bookmaker_odds_are_aggregated_without_duplication(self):
        odds = pd.DataFrame(
            [
                {
                    "match_id": 100,
                    "match_date": "2024-01-01",
                    "bookmaker": "Book A",
                    "player_1_odds": 2.0,
                    "player_2_odds": 1.9,
                    "bookmaker_margin": 0.02,
                    "market_prob_player_1": 0.49,
                    "market_prob_player_2": 0.51,
                },
                {
                    "match_id": 100,
                    "match_date": "2024-01-01",
                    "bookmaker": "Book B",
                    "player_1_odds": 2.2,
                    "player_2_odds": 1.8,
                    "bookmaker_margin": 0.03,
                    "market_prob_player_1": 0.45,
                    "market_prob_player_2": 0.55,
                },
            ]
        )
        dataset = pd.DataFrame(
            [
                {
                    "match_id": 100,
                    "match_date": "2024-01-01",
                    "target_player_1_win": 1,
                }
            ]
        )

        aggregated = aggregate_match_odds(odds)
        merged = attach_odds_to_dataset(dataset, odds)

        self.assertEqual(len(aggregated), 1)
        self.assertEqual(int(aggregated.loc[0, "odds_bookmaker_count"]), 2)
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged.loc[0, "avg_player_1_odds"], 2.1)
        self.assertAlmostEqual(merged.loc[0, "player_1_profit_if_bet"], 1.1)


if __name__ == "__main__":
    unittest.main()
