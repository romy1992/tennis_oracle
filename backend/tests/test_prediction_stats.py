import unittest

from backend.tests.db_helpers import create_session_factory, create_test_engine
from datetime import date, datetime, timezone


from backend.src.entity import Fixture, MatchPrediction, NextFixture
from backend.src.app.services.predictions import (
    compute_daily_prediction_stats,
    compute_prediction_summary,
    get_next_fixtures_with_predictions,
)


class PredictionStatsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_daily_stats_contract_day_zero_is_today(self):
        today = date(2026, 6, 21)
        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=1,
                    event_date=today,
                    odds={
                        "1": {
                            "Home/Away": {
                                "Home": {"Book A": "2.50"},
                                "Away": {"Book A": "1.60"},
                            }
                        }
                    },
                    is_completed=False,
                )
            )
            session.add(
                MatchPrediction(
                    event_key=1,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                    prob_player_1_win=0.7,
                    predicted_winner="First Player",
                    actual_winner="First Player",
                    is_correct=True,
                )
            )
            session.add(
                MatchPrediction(
                    event_key=2,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                    prob_player_1_win=0.4,
                    predicted_winner="Second Player",
                )
            )
            session.add(
                Fixture(
                    id_fixture=2,
                    event_key=2,
                    event_date=today,
                )
            )
            session.commit()

            stats = compute_daily_prediction_stats(
                db=session,
                model_version="v2",
                from_day=0,
                to_day=1,
                reference_date=today,
            )

        self.assertEqual(stats.model_version, "v2")
        self.assertEqual(len(stats.days), 2)
        day_zero = stats.days[0]
        self.assertEqual(day_zero.day_offset, 0)
        self.assertEqual(day_zero.date, today)
        self.assertEqual(day_zero.predictions_total, 2)
        self.assertEqual(day_zero.predictions_resolved, 1)
        self.assertEqual(day_zero.predictions_correct, 1)
        self.assertEqual(day_zero.predictions_lost, 0)
        self.assertAlmostEqual(day_zero.accuracy_pct, 100.0)
        self.assertEqual(day_zero.pending, 1)
        self.assertEqual(day_zero.predictions_with_odds, 1)
        self.assertAlmostEqual(day_zero.avg_predicted_winner_odds, 2.5)
        self.assertAlmostEqual(day_zero.avg_winning_odds, 2.5)
        self.assertAlmostEqual(day_zero.theoretical_profit_units, 1.5)
        self.assertAlmostEqual(day_zero.theoretical_roi_pct, 150.0)

    def test_daily_stats_defaults_to_available_history(self):
        today = date(2026, 6, 21)
        old_date = date(2026, 6, 11)
        with self.Session() as session:
            session.add(
                Fixture(
                    id_fixture=10,
                    event_key=10,
                    event_date=old_date,
                    event_winner="Second Player",
                )
            )
            session.add(
                MatchPrediction(
                    event_key=10,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime(2026, 6, 10, 10, 0, 0),
                    prob_player_1_win=0.4,
                    predicted_winner="Second Player",
                )
            )
            session.commit()

            stats = compute_daily_prediction_stats(
                db=session,
                model_version="v2",
                from_day=0,
                reference_date=today,
            )

        self.assertEqual(stats.days[-1].day_offset, 10)
        self.assertEqual(stats.days[-1].date, old_date)
        self.assertEqual(stats.days[-1].predictions_total, 1)

    def test_summary_aggregates_all_predictions(self):
        with self.Session() as session:
            session.add_all(
                [
                    Fixture(
                        id_fixture=1,
                        event_key=1,
                        odds={
                            "1": {
                                "Home/Away": {
                                    "Home": {"Book A": "2.00"},
                                    "Away": {"Book A": "1.80"},
                                }
                            }
                        },
                    ),
                    Fixture(
                        id_fixture=2,
                        event_key=2,
                        odds={
                            "2": {
                                "Home/Away": {
                                    "Home": {"Book A": "2.40"},
                                    "Away": {"Book A": "1.50"},
                                }
                            }
                        },
                    ),
                    MatchPrediction(
                        event_key=1,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime.now(timezone.utc),
                        prob_player_1_win=0.6,
                        predicted_winner="First Player",
                        actual_winner="First Player",
                        is_correct=True,
                    ),
                    MatchPrediction(
                        event_key=2,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime.now(timezone.utc),
                        prob_player_1_win=0.4,
                        predicted_winner="Second Player",
                        actual_winner="First Player",
                        is_correct=False,
                    ),
                ]
            )
            session.commit()

            summary = compute_prediction_summary(session, model_version="v2")

        self.assertEqual(summary.predictions_total, 2)
        self.assertEqual(summary.predictions_resolved, 2)
        self.assertEqual(summary.predictions_correct, 1)
        self.assertEqual(summary.predictions_lost, 1)
        self.assertAlmostEqual(summary.accuracy_pct, 50.0)
        self.assertEqual(summary.pending, 0)
        self.assertEqual(summary.predictions_with_odds, 2)
        self.assertAlmostEqual(summary.avg_predicted_winner_odds, 1.75)
        self.assertAlmostEqual(summary.avg_winning_odds, 2.0)
        self.assertAlmostEqual(summary.theoretical_profit_units, 0.0)
        self.assertAlmostEqual(summary.theoretical_roi_pct, 0.0)
        self.assertEqual(summary.breakdown[0].model_name, "random_forest")
        self.assertEqual(summary.breakdown[0].predictions_with_odds, 2)
        self.assertAlmostEqual(summary.breakdown[0].theoretical_profit_units, 0.0)

    def test_stats_can_filter_by_model_name(self):
        today = date(2026, 6, 21)
        with self.Session() as session:
            session.add_all(
                [
                    Fixture(id_fixture=1, event_key=1, event_date=today),
                    Fixture(id_fixture=2, event_key=2, event_date=today),
                    MatchPrediction(
                        event_key=1,
                        model_version="v3",
                        model_name="logistic_regression",
                        predicted_at=datetime.now(timezone.utc),
                        prob_player_1_win=0.6,
                        predicted_winner="First Player",
                        actual_winner="First Player",
                        is_correct=True,
                    ),
                    MatchPrediction(
                        event_key=2,
                        model_version="v3",
                        model_name="random_forest",
                        predicted_at=datetime.now(timezone.utc),
                        prob_player_1_win=0.4,
                        predicted_winner="Second Player",
                        actual_winner="First Player",
                        is_correct=False,
                    ),
                ]
            )
            session.commit()

            daily = compute_daily_prediction_stats(
                db=session,
                model_version="v3",
                model_name="logistic_regression",
                from_day=0,
                to_day=0,
                reference_date=today,
            )
            summary = compute_prediction_summary(
                session,
                model_version="v3",
                model_name="logistic_regression",
            )

        self.assertEqual(daily.days[0].predictions_total, 1)
        self.assertEqual(daily.days[0].predictions_correct, 1)
        self.assertEqual(summary.predictions_total, 1)
        self.assertEqual(summary.predictions_correct, 1)
        self.assertEqual(summary.breakdown[0].model_name, "logistic_regression")

    def test_upcoming_predictions_are_read_from_db_only(self):
        today = date(2026, 6, 21)
        with self.Session() as session:
            session.add_all(
                [
                    NextFixture(
                        event_key=1,
                        event_date=today,
                        event_first_player="A",
                        event_second_player="B",
                        odds={
                            "1": {
                                "Home/Away": {
                                    "Home": {"Book A": "2.10"},
                                    "Away": {"Book A": "1.70"},
                                }
                            }
                        },
                        is_completed=False,
                    ),
                    NextFixture(
                        event_key=2,
                        event_date=today,
                        event_first_player="C",
                        event_second_player="D",
                        is_completed=False,
                    ),
                    MatchPrediction(
                        event_key=1,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 20, 10, 0, 0),
                        prob_player_1_win=0.7,
                        predicted_winner="First Player",
                    ),
                ]
            )
            session.commit()

            page = get_next_fixtures_with_predictions(
                db=session,
                model_version="v2",
                model_name="random_forest",
                from_date=today,
                to_date=today,
            )
            fixtures = page.items

        self.assertEqual(page.total, 2)
        self.assertEqual([fixture.event_key for fixture in fixtures], [1, 2])
        self.assertEqual(fixtures[0].prediction.model_name, "random_forest")
        self.assertAlmostEqual(fixtures[0].prediction.confidence, 0.7)
        self.assertAlmostEqual(fixtures[0].prediction.predicted_winner_odds, 2.1)
        self.assertEqual(fixtures[0].prediction.odds_bookmaker_count, 1)
        self.assertIsNone(fixtures[1].prediction)
        self.assertEqual(fixtures[1].prediction_warning, "missing_persisted_prediction")


if __name__ == "__main__":
    unittest.main()
