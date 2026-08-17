import unittest
from datetime import date

from backend.src.app.ml.datasets.odds_builder import FixtureOddsRecord
from backend.src.app.ml.datasets.first_set_winner_odds_builder import (
    FIRST_SET_WINNER_MARKET,
    aggregate_match_first_set_odds,
    average_first_set_winner_odds_from_record,
    first_set_winner_bookmakers,
    first_set_winner_feature_row,
    first_set_winner_rows_from_record,
    odds_records_to_dataframe,
)

MARKET = FIRST_SET_WINNER_MARKET


def _record(odds: dict, *, match_id: int = 100, event_live=0) -> FixtureOddsRecord:
    payload = dict(odds)
    payload.setdefault("Home/Away", {"Home": {"Dummy": "1.90"}, "Away": {"Dummy": "1.90"}})
    return FixtureOddsRecord(
        match_id=match_id,
        match_date=date(2024, 1, 1),
        player_1_id=1,
        player_2_id=2,
        player_1_name="Player A",
        player_2_name="Player B",
        odds=payload,
        event_live=event_live,
    )


class FirstSetWinnerBookmakersTest(unittest.TestCase):
    def test_extracts_common_bookmakers(self):
        payload = {
            "Home/Away": {"Home": {"Dummy": "1.90"}, "Away": {"Dummy": "1.90"}},
            MARKET: {
                "Home": {"1xBet": "1.61", "bet365": "1.65"},
                "Away": {"1xBet": "2.18", "bet365": "2.10"},
            },
        }
        self.assertEqual(first_set_winner_bookmakers(payload), ["1xBet", "bet365"])

    def test_missing_market_returns_empty_list(self):
        self.assertEqual(first_set_winner_bookmakers({"Home/Away": {}}), [])


class FirstSetWinnerRowsFromRecordTest(unittest.TestCase):
    def test_outputs_one_row_per_common_bookmaker_with_no_vig_probabilities(self):
        record = _record(
            {
                MARKET: {
                    "Home": {"1xBet": "1.61", "bet365": "1.65", "OnlyHome": "1.50"},
                    "Away": {"1xBet": "2.18", "bet365": "2.10"},
                }
            }
        )

        rows = first_set_winner_rows_from_record(record)

        self.assertEqual({row["bookmaker"] for row in rows}, {"1xBet", "bet365"})
        xbet = next(row for row in rows if row["bookmaker"] == "1xBet")
        self.assertAlmostEqual(xbet["player_1_odds"], 1.61)
        self.assertAlmostEqual(xbet["player_2_odds"], 2.18)
        self.assertAlmostEqual(
            xbet["market_prob_player_1"] + xbet["market_prob_player_2"], 1.0, places=6,
        )

    def test_live_records_are_excluded(self):
        record = _record(
            {MARKET: {"Home": {"1xBet": "1.61"}, "Away": {"1xBet": "2.18"}}},
            event_live=1,
        )
        self.assertEqual(first_set_winner_rows_from_record(record), [])

    def test_bad_odds_are_excluded(self):
        record = _record({MARKET: {"Home": {"Bad": "1.00"}, "Away": {"Bad": "1.95"}}})
        self.assertEqual(first_set_winner_rows_from_record(record), [])


class AverageFirstSetWinnerOddsTest(unittest.TestCase):
    def test_averages_common_bookmakers(self):
        record = _record(
            {
                MARKET: {
                    "Home": {"A": "1.50", "B": "1.70"},
                    "Away": {"A": "2.50", "B": "2.10"},
                }
            }
        )
        avg = average_first_set_winner_odds_from_record(record)
        self.assertIsNotNone(avg)
        self.assertAlmostEqual(avg.avg_player_1_odds, 1.60)
        self.assertAlmostEqual(avg.avg_player_2_odds, 2.30)
        self.assertEqual(avg.odds_bookmaker_count, 2)

    def test_missing_market_returns_none(self):
        self.assertIsNone(average_first_set_winner_odds_from_record(_record({})))


class FirstSetWinnerFeatureRowTest(unittest.TestCase):
    def test_returns_six_aggregate_columns(self):
        payload = {
            "Home/Away": {"Home": {"Dummy": "1.90"}, "Away": {"Dummy": "1.90"}},
            MARKET: {"Home": {"A": "1.80"}, "Away": {"A": "2.00"}},
        }
        row = first_set_winner_feature_row(
            event_key=100, match_date=date(2024, 1, 1), odds=payload,
        )
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["avg_first_set_player_1_odds"], 1.80)
        self.assertAlmostEqual(row["avg_first_set_player_2_odds"], 2.00)
        self.assertEqual(row["first_set_odds_bookmaker_count"], 1)

    def test_returns_none_without_market(self):
        self.assertIsNone(
            first_set_winner_feature_row(
                event_key=100,
                match_date=date(2024, 1, 1),
                odds={"Home/Away": {"Home": {"A": "1.9"}, "Away": {"A": "1.9"}}},
            )
        )


class AggregateMatchFirstSetOddsTest(unittest.TestCase):
    def test_groups_by_match(self):
        records = [
            _record(
                {MARKET: {"Home": {"A": "1.50"}, "Away": {"A": "2.50"}}},
                match_id=1,
            ),
            _record(
                {MARKET: {"Home": {"A": "1.80", "B": "1.60"}, "Away": {"A": "2.00", "B": "2.20"}}},
                match_id=2,
            ),
        ]
        aggregated = aggregate_match_first_set_odds(odds_records_to_dataframe(records))
        self.assertEqual(len(aggregated), 2)
        match_2 = aggregated.loc[aggregated["match_id"] == 2].iloc[0]
        self.assertAlmostEqual(match_2["avg_first_set_player_1_odds"], 1.70)
        self.assertEqual(match_2["first_set_odds_bookmaker_count"], 2)
