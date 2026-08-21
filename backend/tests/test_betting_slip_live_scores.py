"""Live score polling and persisted betting-slip settlement tests."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time
from unittest.mock import patch

from sqlalchemy import select

from backend.src.app.services.betting_slip_live_scores import (
    run_betting_slip_live_poll_once,
)
from backend.src.entity import BettingSlip, BettingSlipPick, NextFixture
from backend.tests.auth_helpers import make_test_settings
from backend.tests.db_helpers import create_session_factory, create_test_engine


class BettingSlipLiveScoresTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.today = date.today()
        self.settings = make_test_settings(
            betting_slip_timezone="Europe/Rome",
            betting_slip_live_poll_enabled=True,
        )

    def tearDown(self):
        self.engine.dispose()

    def _seed_opposite_picks(self, session) -> None:
        session.add(
            NextFixture(
                event_key=991,
                event_date=self.today,
                event_time=time(14, 0),
                event_first_player="Jannik Sinner",
                event_second_player="Carlos Alcaraz",
                event_status="Not Started",
                event_type_type="ATP Singles",
                is_completed=False,
            )
        )
        for index, predicted_winner in enumerate(
            ("First Player", "Second Player"), start=1
        ):
            slip = BettingSlip(
                slip_date=self.today,
                slip_key=f"test_{index}",
                label=f"Test {index}",
                description="Live settlement",
                model_version="v2",
                model_name="random_forest",
                pick_count=1,
                combined_odds=2.0,
                generated_at=datetime.combine(self.today, time(9, 0)),
            )
            session.add(slip)
            session.flush()
            session.add(
                BettingSlipPick(
                    betting_slip_id=slip.id,
                    event_key=991,
                    market="match_winner",
                    event_date=self.today,
                    event_time=time(14, 0),
                    player_1_name="Jannik Sinner",
                    player_2_name="Carlos Alcaraz",
                    predicted_winner=predicted_winner,
                    predicted_winner_label=(
                        "Jannik Sinner"
                        if predicted_winner == "First Player"
                        else "Carlos Alcaraz"
                    ),
                    odds=2.0,
                    sort_order=0,
                    outcome="pending",
                )
            )
        session.commit()

    @patch("backend.src.app.services.betting_slip_live_scores.request_api")
    def test_updates_daily_fixture_even_when_it_is_not_in_a_slip(self, request_api) -> None:
        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=992,
                    event_date=self.today,
                    event_time=time(15, 0),
                    event_first_player="Lorenzo Musetti",
                    event_second_player="Alexander Zverev",
                    event_status="Not Started",
                    event_type_type="ATP Singles",
                    is_completed=False,
                )
            )
            session.commit()
            request_api.return_value = [
                {
                    "event_key": 992,
                    "event_date": self.today.isoformat(),
                    "event_type_type": "ATP Singles",
                    "event_status": "Set 1",
                    "event_live": "1",
                    "event_game_result": "15 - 30",
                    "event_serve": "Second Player",
                    "event_final_result": "0 - 0",
                    "scores": [],
                }
            ]

            summary = run_betting_slip_live_poll_once(
                session,
                target_date=self.today,
                settings=self.settings,
                now=datetime.combine(self.today, time(15, 10)),
            )
            fixture = session.scalar(
                select(NextFixture).where(NextFixture.event_key == 992)
            )

            self.assertEqual(summary["candidates"], 1)
            self.assertEqual(summary["updated"], 1)
            self.assertEqual(fixture.event_live, "1")
            self.assertEqual(fixture.live_score["current_game"], "15 - 30")

    @patch("backend.src.app.services.betting_slip_live_scores.request_api")
    def test_started_score_then_completed_settles_won_and_lost(self, request_api) -> None:
        with self.Session() as session:
            self._seed_opposite_picks(session)
            request_api.return_value = [
                {
                    "event_key": 991,
                    "event_date": self.today.isoformat(),
                    "event_type_type": "ATP Singles",
                    "event_status": "Set 2",
                    "event_live": "1",
                    "event_game_result": "30 - 15",
                    "event_serve": "First Player",
                    "event_final_result": "1 - 0",
                    "scores": [
                        {
                            "score_first": "6",
                            "score_second": "4",
                            "score_set": "1",
                        }
                    ],
                }
            ]
            started = run_betting_slip_live_poll_once(
                session,
                target_date=self.today,
                settings=self.settings,
                now=datetime.combine(self.today, time(14, 30)),
            )
            fixture = session.scalar(
                select(NextFixture).where(NextFixture.event_key == 991)
            )
            outcomes = list(
                session.scalars(
                    select(BettingSlipPick.outcome).order_by(BettingSlipPick.id)
                ).all()
            )
            self.assertEqual(started["updated"], 1)
            self.assertEqual(outcomes, ["pending", "pending"])
            self.assertEqual(fixture.live_score["current_game"], "30 - 15")
            self.assertEqual(fixture.live_score["sets"][0]["score_first"], "6")

            request_api.return_value = [
                {
                    "event_key": 991,
                    "event_date": self.today.isoformat(),
                    "event_type_type": "ATP Singles",
                    "event_status": "Finished",
                    "event_live": "0",
                    "event_winner": "First Player",
                    "event_final_result": "2 - 0",
                    "event_game_result": "",
                    "scores": [
                        {
                            "score_first": "6",
                            "score_second": "4",
                            "score_set": "1",
                        },
                        {
                            "score_first": "6",
                            "score_second": "3",
                            "score_set": "2",
                        },
                    ],
                }
            ]
            completed = run_betting_slip_live_poll_once(
                session,
                target_date=self.today,
                settings=self.settings,
                now=datetime.combine(self.today, time(16, 0)),
            )
            picks = list(
                session.scalars(select(BettingSlipPick).order_by(BettingSlipPick.id)).all()
            )
            self.assertEqual(completed["promoted"], 1)
            self.assertEqual([pick.outcome for pick in picks], ["won", "lost"])
            self.assertTrue(all(pick.settled_at is not None for pick in picks))


if __name__ == "__main__":
    unittest.main()
