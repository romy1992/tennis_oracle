"""Tests for match lifecycle classification and void settlement helpers."""

from __future__ import annotations

import unittest

from backend.src.app.services.match_lifecycle import (
    classify_match_lifecycle,
    is_void_for_betting,
    match_lifecycle_label,
)
from backend.src.app.services.betting_slips import (
    _effective_combined_odds,
    _resolve_pick_status,
    _resolve_slip_status,
    _slip_profit_units,
)
from backend.src.app.schemas.betting_slips import BettingSlipPickRead, BettingSlipRead
from backend.src.entity import BettingSlipPick


class MatchLifecycleTest(unittest.TestCase):
    def test_cancelled_without_winner_is_voidable(self):
        status = classify_match_lifecycle(event_status="Cancelled")
        self.assertEqual(status, "cancelled")
        self.assertTrue(is_void_for_betting(status, None))
        self.assertEqual(match_lifecycle_label(status), "Annullata")

    def test_postponed_is_not_void(self):
        status = classify_match_lifecycle(event_status="Postponed")
        self.assertEqual(status, "postponed")
        self.assertFalse(is_void_for_betting(status, None))

    def test_abandoned_without_winner_is_voidable(self):
        status = classify_match_lifecycle(event_status="Abandoned")
        self.assertEqual(status, "abandoned")
        self.assertTrue(is_void_for_betting(status, None))

    def test_finished_without_winner_is_unknown_problem_voidable(self):
        status = classify_match_lifecycle(event_status="Finished", event_winner=None)
        self.assertEqual(status, "unknown_problem")
        self.assertTrue(is_void_for_betting(status, None))

    def test_walkover_with_winner_settleable(self):
        status = classify_match_lifecycle(
            event_status="Walkover",
            event_winner="First Player",
        )
        self.assertEqual(status, "walkover")
        self.assertFalse(is_void_for_betting(status, "First Player"))

    def test_walkover_without_winner_voidable(self):
        status = classify_match_lifecycle(event_status="Walkover")
        self.assertEqual(status, "walkover")
        self.assertTrue(is_void_for_betting(status, None))

    def test_retired_with_winner_settleable(self):
        status = classify_match_lifecycle(
            event_status="Retired",
            event_winner="Second Player",
        )
        self.assertEqual(status, "retired")
        self.assertFalse(is_void_for_betting(status, "Second Player"))

    def test_live_set_status(self):
        self.assertEqual(classify_match_lifecycle(event_status="Set 2"), "live")

    def test_unmapped_status_stays_scheduled_non_void(self):
        status = classify_match_lifecycle(event_status="SomeWeirdFlag")
        self.assertEqual(status, "scheduled")
        self.assertFalse(is_void_for_betting(status, None))


class VoidSettlementTest(unittest.TestCase):
    def _pick(self, predicted: str = "First Player") -> BettingSlipPick:
        return BettingSlipPick(
            betting_slip_id=1,
            event_key=1,
            predicted_winner=predicted,
            sort_order=0,
        )

    def test_pick_void_when_cancelled(self):
        self.assertEqual(
            _resolve_pick_status(self._pick(), None, match_lifecycle_status="cancelled"),
            ("void", None),
        )

    def test_pick_pending_when_postponed(self):
        self.assertEqual(
            _resolve_pick_status(self._pick(), None, match_lifecycle_status="postponed"),
            ("pending", None),
        )

    def test_walkover_with_winner_won_lost(self):
        self.assertEqual(
            _resolve_pick_status(
                self._pick("First Player"),
                "First Player",
                match_lifecycle_status="walkover",
            ),
            ("won", True),
        )
        self.assertEqual(
            _resolve_pick_status(
                self._pick("First Player"),
                "Second Player",
                match_lifecycle_status="walkover",
            ),
            ("lost", False),
        )

    def test_slip_won_ignoring_void_legs(self):
        self.assertEqual(_resolve_slip_status(["won", "void", "won"]), "won")

    def test_slip_lost_with_void_present(self):
        self.assertEqual(_resolve_slip_status(["won", "void", "lost"]), "lost")

    def test_slip_pending_with_void_present(self):
        self.assertEqual(_resolve_slip_status(["won", "void", "pending"]), "pending")

    def test_slip_all_void(self):
        self.assertEqual(_resolve_slip_status(["void", "void"]), "void")

    def test_effective_odds_exclude_void(self):
        picks = [
            BettingSlipPickRead(
                event_key=1,
                predicted_winner="First Player",
                odds=1.5,
                pick_status="won",
            ),
            BettingSlipPickRead(
                event_key=2,
                predicted_winner="First Player",
                odds=1.8,
                pick_status="void",
            ),
            BettingSlipPickRead(
                event_key=3,
                predicted_winner="First Player",
                odds=2.0,
                pick_status="won",
            ),
        ]
        self.assertEqual(_effective_combined_odds(picks), 3.0)

    def test_profit_uses_effective_odds(self):
        slip = BettingSlipRead(
            id="play_safe",
            slip_key="play_safe",
            label="Play · Sicura",
            pick_count=3,
            combined_odds=5.4,
            potential_return=54.0,
            potential_profit=44.0,
            slip_status="won",
            effective_combined_odds=3.0,
        )
        self.assertEqual(_slip_profit_units(slip, 10.0), 20.0)

    def test_void_slip_profit_zero(self):
        slip = BettingSlipRead(
            id="play_safe",
            slip_key="play_safe",
            label="Play · Sicura",
            pick_count=2,
            combined_odds=3.0,
            potential_return=30.0,
            potential_profit=20.0,
            slip_status="void",
            effective_combined_odds=None,
        )
        self.assertEqual(_slip_profit_units(slip, 10.0), 0.0)


if __name__ == "__main__":
    unittest.main()
