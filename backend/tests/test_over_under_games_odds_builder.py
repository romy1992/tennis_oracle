import unittest
from datetime import date

import pandas as pd

from backend.src.app.ml.datasets.odds_builder import FixtureOddsRecord
from backend.src.app.ml.datasets.over_under_games_odds_builder import (
    aggregate_match_over_under_odds,
    attach_over_under_odds_to_dataset,
    average_over_under_games_odds_from_record,
    inspect_over_under_lines,
    line_key,
    odds_records_to_dataframe,
    over_under_games_bookmakers,
    over_under_games_rows_from_record,
)

MARKET = "Over/Under by Games in Match"
OVER_SEL = "Over/Under by Games in Match Over"
UNDER_SEL = "Over/Under by Games in Match Under"


def _record(odds: dict, *, match_id: int = 100, event_live=0) -> FixtureOddsRecord:
    # Il payload reale ha SEMPRE decine di mercati (Home/Away quasi al 100%):
    # se il mock avesse una sola chiave top-level, l'euristica di
    # normalized_odds_payload pensata per il caso "{match_id: {...}}"
    # (len(payload) == 1) sbuccerebbe erroneamente un livello di troppo. Si
    # inietta quindi sempre un Home/Away fittizio, a meno che il test non lo
    # sovrascriva esplicitamente (setdefault).
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


class LineKeyTest(unittest.TestCase):
    def test_half_point_line_is_kept_as_is(self):
        self.assertEqual(line_key(20.5), "20.5")

    def test_integer_line_is_formatted_without_decimal(self):
        self.assertEqual(line_key(20.0), "20")
        self.assertEqual(line_key(21), "21")


class OverUnderGamesBookmakersTest(unittest.TestCase):
    def test_extracts_common_bookmakers_for_requested_line(self):
        payload = {
            "Home/Away": {"Home": {"Dummy": "1.90"}, "Away": {"Dummy": "1.90"}},
            MARKET: {
                OVER_SEL: {"20.5": {"Betfair": "1.82", "Superbet": "1.85"}, "21.5": {"Superbet": "1.92"}},
                UNDER_SEL: {"20.5": {"Betfair": "1.95", "Superbet": "1.88"}, "21.5": {"Superbet": "1.78"}},
            }
        }
        self.assertEqual(over_under_games_bookmakers(payload, line=20.5), ["Betfair", "Superbet"])
        self.assertEqual(over_under_games_bookmakers(payload, line=21.5), ["Superbet"])

    def test_missing_market_returns_empty_list(self):
        self.assertEqual(over_under_games_bookmakers({"Home/Away": {}}, line=20.5), [])

    def test_line_absent_returns_empty_list(self):
        payload = {
            "Home/Away": {"Home": {"Dummy": "1.90"}, "Away": {"Dummy": "1.90"}},
            MARKET: {OVER_SEL: {"20.5": {"Betfair": "1.82"}}, UNDER_SEL: {"20.5": {"Betfair": "1.95"}}},
        }
        self.assertEqual(over_under_games_bookmakers(payload, line=25.5), [])


class OverUnderGamesRowsFromRecordTest(unittest.TestCase):
    def test_outputs_one_row_per_common_bookmaker_with_no_vig_probabilities(self):
        record = _record(
            {
                MARKET: {
                    OVER_SEL: {"20.5": {"Betfair": "1.82", "Superbet": "1.85", "OnlyOver": "1.90"}},
                    UNDER_SEL: {"20.5": {"Betfair": "1.95", "Superbet": "1.88"}},
                }
            }
        )

        rows = over_under_games_rows_from_record(record, line=20.5)

        self.assertEqual({row["bookmaker"] for row in rows}, {"Betfair", "Superbet"})
        betfair_row = next(row for row in rows if row["bookmaker"] == "Betfair")
        self.assertAlmostEqual(betfair_row["over_odds"], 1.82)
        self.assertAlmostEqual(betfair_row["under_odds"], 1.95)
        self.assertAlmostEqual(
            betfair_row["market_prob_over"] + betfair_row["market_prob_under"], 1.0, places=6,
        )
        self.assertEqual(betfair_row["line"], 20.5)

    def test_live_records_are_excluded(self):
        record = _record(
            {MARKET: {OVER_SEL: {"20.5": {"Betfair": "1.82"}}, UNDER_SEL: {"20.5": {"Betfair": "1.95"}}}},
            event_live=1,
        )
        self.assertEqual(over_under_games_rows_from_record(record, line=20.5), [])

    def test_integer_line_lookup_uses_integer_key(self):
        record = _record({MARKET: {OVER_SEL: {"21": {"Pncl": "1.90"}}, UNDER_SEL: {"21": {"Pncl": "1.88"}}}})

        rows = over_under_games_rows_from_record(record, line=21.0)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bookmaker"], "Pncl")

    def test_bad_odds_are_excluded(self):
        record = _record(
            {MARKET: {OVER_SEL: {"20.5": {"Bad": "1.00"}}, UNDER_SEL: {"20.5": {"Bad": "1.95"}}}}
        )
        self.assertEqual(over_under_games_rows_from_record(record, line=20.5), [])


class AverageOverUnderGamesOddsTest(unittest.TestCase):
    def test_averages_across_bookmakers(self):
        record = _record(
            {
                MARKET: {
                    OVER_SEL: {"20.5": {"Betfair": "1.80", "Superbet": "1.90"}},
                    UNDER_SEL: {"20.5": {"Betfair": "2.00", "Superbet": "1.90"}},
                }
            }
        )

        average = average_over_under_games_odds_from_record(record, line=20.5)

        self.assertIsNotNone(average)
        self.assertAlmostEqual(average.avg_over_odds, 1.85)
        self.assertAlmostEqual(average.avg_under_odds, 1.95)
        self.assertEqual(average.odds_bookmaker_count, 2)

    def test_no_market_returns_none(self):
        record = _record({"Home/Away": {"Home": {"Book": "1.5"}, "Away": {"Book": "2.5"}}})
        self.assertIsNone(average_over_under_games_odds_from_record(record, line=20.5))


class AggregateAndAttachTest(unittest.TestCase):
    def test_aggregate_and_attach_to_dataset(self):
        record_1 = _record(
            {
                MARKET: {
                    OVER_SEL: {"20.5": {"Betfair": "1.80", "Superbet": "1.90"}},
                    UNDER_SEL: {"20.5": {"Betfair": "2.00", "Superbet": "1.90"}},
                }
            },
            match_id=100,
        )
        odds_df = odds_records_to_dataframe([record_1], line=20.5)
        aggregated = aggregate_match_over_under_odds(odds_df)

        self.assertEqual(len(aggregated), 1)
        self.assertEqual(int(aggregated.loc[0, "odds_bookmaker_count_ou_games"]), 2)
        self.assertAlmostEqual(aggregated.loc[0, "avg_over_odds"], 1.85)

        dataset = pd.DataFrame([{"match_id": 100, "match_date": "2024-01-01", "target_total_games": 22}])
        merged = attach_over_under_odds_to_dataset(dataset, odds_df)

        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged.loc[0, "avg_over_odds"], 1.85)
        self.assertAlmostEqual(merged.loc[0, "avg_under_odds"], 1.95)

    def test_empty_odds_dataframe_produces_expected_columns(self):
        empty = odds_records_to_dataframe([], line=20.5)
        aggregated = aggregate_match_over_under_odds(empty)
        self.assertIn("avg_over_odds", aggregated.columns)
        self.assertEqual(len(aggregated), 0)


class InspectOverUnderLinesTest(unittest.TestCase):
    def test_counts_matches_per_line(self):
        record_1 = _record(
            {MARKET: {OVER_SEL: {"20.5": {"Betfair": "1.80"}}, UNDER_SEL: {"20.5": {"Betfair": "2.00"}}}},
            match_id=1,
        )
        record_2 = _record(
            {
                MARKET: {
                    OVER_SEL: {"20.5": {"Superbet": "1.85"}, "21.5": {"Superbet": "1.95"}},
                    UNDER_SEL: {"20.5": {"Superbet": "1.90"}, "21.5": {"Superbet": "1.80"}},
                }
            },
            match_id=2,
        )
        counts = inspect_over_under_lines([record_1, record_2])
        self.assertEqual(counts.get("20.5"), 2)
        self.assertEqual(counts.get("21.5"), 1)


if __name__ == "__main__":
    unittest.main()




