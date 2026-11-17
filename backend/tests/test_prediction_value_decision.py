"""Decisione di valore del vincitore partita esposta da MatchPredictionRead.

`value_decision` / `void_odds` / `adjusted_probability` devono essere quelli del
motore (probabilita' ridotta verso il mercato), coerenti con
`analyze_single_match_value` e con `telegram/fixture_value.py`."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from backend.src.app.main import app
from backend.src.app.ml.datasets.odds_builder import MatchWinnerOddsAverage
from backend.src.app.services.predictions import _prediction_read
from backend.src.app.services.single_match_value import (
    DEFAULT_MIN_EDGE_PERCENT,
    analyze_single_match_value,
    classify_single_bet_value,
    match_winner_value,
)
from backend.src.app.telegram.fixture_value import enrich_fixture_value
from backend.src.entity import MatchPrediction, NextFixture
from backend.tests.auth_helpers import clear_settings_override, make_test_settings, override_settings
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client


def _prediction(prob_player_1_win: float, predicted_winner: str, event_key: int = 1) -> MatchPrediction:
    return MatchPrediction(
        event_key=event_key,
        model_version="v2",
        model_name="random_forest",
        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
        prob_player_1_win=prob_player_1_win,
        predicted_winner=predicted_winner,
    )


def _odds_payload(event_key: int, home: str, away: str) -> dict:
    return {
        str(event_key): {
            "Home/Away": {
                "Home": {"Book A": home},
                "Away": {"Book A": away},
            }
        }
    }


class MatchWinnerValueTest(unittest.TestCase):
    def test_example_74_vs_55_at_155_is_no_bet(self):
        value = match_winner_value(
            predicted_winner="First Player",
            prob_player_1_win=0.74,
            market_odds=1.55,
            market_fair_probability=0.55,
        )
        self.assertEqual(value.value_decision, "NO BET")
        self.assertAlmostEqual(value.adjusted_probability, 0.645)
        self.assertAlmostEqual(value.void_odds, 1.5504, places=4)
        # Sulla probabilita' grezza (1/0.74) la stessa quota sarebbe PLAY.
        raw = classify_single_bet_value(
            market_odds=1.55,
            void_odds=1.0 / 0.74,
            min_edge_percent=DEFAULT_MIN_EDGE_PERCENT,
        )
        self.assertEqual(raw, "PLAY")

    def test_play_case(self):
        value = match_winner_value(
            predicted_winner="First Player",
            prob_player_1_win=0.70,
            market_odds=1.70,
            market_fair_probability=0.55,
        )
        # p_adj 0.625 -> void 1.60, soglia PLAY 1.632.
        self.assertEqual(value.value_decision, "PLAY")
        self.assertAlmostEqual(value.void_odds, 1.6)
        self.assertAlmostEqual(value.adjusted_probability, 0.625)

    def test_second_player_uses_its_own_probability(self):
        value = match_winner_value(
            predicted_winner="Second Player",
            prob_player_1_win=0.30,
            market_odds=1.70,
            market_fair_probability=0.55,
        )
        self.assertEqual(value.value_decision, "PLAY")
        self.assertAlmostEqual(value.adjusted_probability, 0.625)

    def test_missing_odds_gives_no_decision(self):
        value = match_winner_value(
            predicted_winner="First Player",
            prob_player_1_win=0.74,
            market_odds=None,
            market_fair_probability=None,
        )
        self.assertIsNone(value.value_decision)
        self.assertIsNone(value.void_odds)
        self.assertIsNone(value.adjusted_probability)

    def test_missing_market_probability_is_no_bet(self):
        value = match_winner_value(
            predicted_winner="First Player",
            prob_player_1_win=0.74,
            market_odds=1.80,
            market_fair_probability=None,
        )
        self.assertEqual(value.value_decision, "NO BET")
        self.assertIsNone(value.void_odds)
        self.assertIsNone(value.adjusted_probability)

    def test_missing_model_probability_or_winner_gives_no_decision(self):
        for winner, probability in (("First Player", None), (None, 0.7), ("Draw", 0.7)):
            value = match_winner_value(
                predicted_winner=winner,
                prob_player_1_win=probability,
                market_odds=1.80,
                market_fair_probability=0.5,
            )
            self.assertIsNone(value.value_decision)
            self.assertIsNone(value.void_odds)


class PredictionReadValueCoherenceTest(unittest.TestCase):
    """Stesso input -> stessa decisione del motore in tutti i percorsi."""

    CASES = (
        # prob_player_1_win, predicted_winner, quota P1, quota P2
        (0.74, "First Player", 1.55, 1.8945),  # NO BET (esempio)
        (0.70, "First Player", 2.10, 1.75),  # PLAY
        (0.60, "First Player", 1.80, 2.00),  # BORDERLINE
        (0.30, "Second Player", 2.10, 1.75),  # PLAY
        (0.30, "Second Player", 2.60, 1.45),  # NO BET
    )

    def _paths(self, prob_player_1_win, predicted_winner, odds):
        read = _prediction_read(_prediction(prob_player_1_win, predicted_winner), odds)
        smva = analyze_single_match_value(
            match_id=1,
            event_date=None,
            event_time=None,
            tournament_name=None,
            player_a="A",
            player_b="B",
            predicted_winner=predicted_winner,
            prob_player_1_win=prob_player_1_win,
            odds=odds,
        )
        telegram = enrich_fixture_value(
            {"event_key": 1, "prediction": read.model_dump(mode="json")},
            min_edge_percent=DEFAULT_MIN_EDGE_PERCENT,
        )
        return read, smva, telegram

    def test_decision_matches_single_match_value_and_telegram(self):
        seen = set()
        for p1, winner, odd_1, odd_2 in self.CASES:
            with self.subTest(p1=p1, winner=winner, odd_1=odd_1, odd_2=odd_2):
                odds = MatchWinnerOddsAverage(odd_1, odd_2, 3)
                read, smva, telegram = self._paths(p1, winner, odds)
                self.assertIsNotNone(read.value_decision)
                self.assertEqual(read.value_decision, smva.decision)
                self.assertEqual(read.value_decision, telegram["value_decision"])
                self.assertAlmostEqual(read.void_odds, smva.void_odds, places=4)
                self.assertAlmostEqual(read.void_odds, telegram["void_odds"], places=4)
                seen.add(read.value_decision)
        self.assertEqual(seen, {"PLAY", "BORDERLINE", "NO BET"})

    def test_published_probabilities_stay_raw(self):
        odds = MatchWinnerOddsAverage(1.55, 1.8945, 3)
        read = _prediction_read(_prediction(0.74, "First Player"), odds)
        self.assertAlmostEqual(read.prob_player_1_win, 0.74)
        self.assertAlmostEqual(read.confidence, 0.74)
        self.assertAlmostEqual(read.predicted_winner_odds, 1.55)
        self.assertAlmostEqual(read.predicted_winner_market_probability, 0.55, places=4)
        self.assertEqual(read.value_decision, "NO BET")
        self.assertAlmostEqual(read.void_odds, 1.5504, places=4)

    def test_missing_market_probability_matches_single_match_value(self):
        # Quota del vincitore presente, lato avversario non utilizzabile: nessuna
        # probabilita' no-vig. Il motore (SMVA) classifica NO BET.
        odds = MatchWinnerOddsAverage(1.80, 0.0, 1)
        read, smva, telegram = self._paths(0.74, "First Player", odds)
        self.assertIsNone(read.predicted_winner_market_probability)
        self.assertEqual(read.value_decision, "NO BET")
        self.assertEqual(read.value_decision, smva.decision)
        self.assertIsNone(read.void_odds)
        # telegram/fixture_value non valuta senza probabilita' di mercato
        # (nessuna decisione): mai un PLAY/BORDERLINE in contrasto col motore.
        self.assertNotIn(telegram.get("value_decision"), {"PLAY", "BORDERLINE"})

    def test_missing_odds_gives_no_decision(self):
        read = _prediction_read(_prediction(0.74, "First Player"), None)
        self.assertIsNone(read.predicted_winner_odds)
        self.assertIsNone(read.value_decision)
        self.assertIsNone(read.void_odds)
        self.assertIsNone(read.adjusted_probability)


class NextFixturesPredictionsValueRouteTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        override_settings(make_test_settings(rate_limit_enabled=False))
        self.client = make_api_client(app, self.Session)

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_route_exposes_engine_value_decision(self):
        today = date.today()
        with self.Session() as session:
            session.add_all(
                [
                    NextFixture(
                        event_key=200,
                        event_date=today,
                        event_first_player="A",
                        event_second_player="B",
                        odds=_odds_payload(200, "1.55", "1.8945"),
                        is_completed=False,
                    ),
                    NextFixture(
                        event_key=201,
                        event_date=today,
                        event_first_player="C",
                        event_second_player="D",
                        odds=_odds_payload(201, "2.10", "1.75"),
                        is_completed=False,
                    ),
                    NextFixture(
                        event_key=202,
                        event_date=today,
                        event_first_player="E",
                        event_second_player="F",
                        is_completed=False,
                    ),
                    NextFixture(
                        event_key=203,
                        event_date=today,
                        event_first_player="G",
                        event_second_player="H",
                        odds=_odds_payload(203, "2.10", "1.75"),
                        is_completed=False,
                    ),
                    _prediction(0.74, "First Player", event_key=200),
                    _prediction(0.70, "First Player", event_key=201),
                    _prediction(0.74, "First Player", event_key=202),
                ]
            )
            session.commit()

        response = self.client.get(
            "/api/next-fixtures/predictions",
            params={"model_version": "v2", "model_name": "random_forest"},
        )
        self.assertEqual(response.status_code, 200)
        items = {item["event_key"]: item for item in response.json()["items"]}

        no_bet = items[200]["prediction"]
        self.assertEqual(no_bet["value_decision"], "NO BET")
        self.assertAlmostEqual(no_bet["void_odds"], 1.5504, places=4)
        self.assertAlmostEqual(no_bet["adjusted_probability"], 0.645, places=4)
        self.assertAlmostEqual(no_bet["prob_player_1_win"], 0.74)
        self.assertAlmostEqual(no_bet["predicted_winner_odds"], 1.55)

        play = items[201]["prediction"]
        self.assertEqual(play["value_decision"], "PLAY")
        self.assertAlmostEqual(play["void_odds"], 1.7323, places=4)

        without_odds = items[202]["prediction"]
        self.assertIsNone(without_odds["predicted_winner_odds"])
        self.assertIsNone(without_odds["value_decision"])
        self.assertIsNone(without_odds["void_odds"])
        self.assertIsNone(without_odds["adjusted_probability"])

        self.assertIsNone(items[203]["prediction"])
        self.assertEqual(items[203]["prediction_warning"], "missing_persisted_prediction")


if __name__ == "__main__":
    unittest.main()
