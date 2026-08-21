"""Tests for match lifecycle classification and simulated-bet settlement."""

from __future__ import annotations

import unittest

from backend.src.app.services.match_lifecycle import (
    classify_match_lifecycle,
    is_eligible_for_slip_pool,
    is_void_for_betting,
    match_lifecycle_label,
    normalize_lifecycle_status,
    resolve_slip_status_from_picks,
    settle_simulated_bet,
    settlement_policy,
    slip_profit_units,
)
from backend.src.app.services.betting_slips import (
    _effective_combined_odds,
    _resolve_pick_status,
    _resolve_slip_status,
    _slip_profit_units,
)
from backend.src.app.schemas.betting_slips import BettingSlipPickRead, BettingSlipRead
from backend.src.entity import BettingSlipPick

ALL_STATUSES = (
    "upcoming",
    "started",
    "completed",
    "postponed",
    "cancelled",
    "retired",
    "walkover",
    "abandoned",
    "unknown",
)


class MatchLifecycleClassificationTest(unittest.TestCase):
    def test_upcoming_default(self):
        status = classify_match_lifecycle(event_status=None)
        self.assertEqual(status, "upcoming")
        self.assertFalse(is_void_for_betting(status, None))
        self.assertEqual(match_lifecycle_label(status), "Da giocare")

    def test_started_from_live_and_set(self):
        self.assertEqual(classify_match_lifecycle(event_status="Set 2"), "started")
        self.assertEqual(
            classify_match_lifecycle(event_status="Not Started", event_live="1"),
            "started",
        )

    def test_not_started_status_is_upcoming_and_slip_pool_eligible(self):
        # "Not Started" is the standard API-Tennis status for every future
        # fixture; it must not be misread as the live "started" lifecycle
        # just because it contains that substring.
        status = classify_match_lifecycle(event_status="Not Started")
        self.assertEqual(status, "upcoming")
        self.assertTrue(is_eligible_for_slip_pool(status))

    def test_completed_with_winner(self):
        status = classify_match_lifecycle(
            event_status="Finished",
            event_winner="First Player",
        )
        self.assertEqual(status, "completed")
        self.assertFalse(is_void_for_betting(status, "First Player"))

    def test_postponed_is_not_void(self):
        status = classify_match_lifecycle(event_status="Postponed")
        self.assertEqual(status, "postponed")
        self.assertFalse(is_void_for_betting(status, None))

    def test_cancelled_without_winner_is_voidable(self):
        status = classify_match_lifecycle(event_status="Cancelled")
        self.assertEqual(status, "cancelled")
        self.assertTrue(is_void_for_betting(status, None))
        self.assertEqual(match_lifecycle_label(status), "Annullata")

    def test_abandoned_without_winner_is_voidable(self):
        status = classify_match_lifecycle(event_status="Abandoned")
        self.assertEqual(status, "abandoned")
        self.assertTrue(is_void_for_betting(status, None))

    def test_finished_without_winner_is_unknown_voidable(self):
        status = classify_match_lifecycle(event_status="Finished", event_winner=None)
        self.assertEqual(status, "unknown")
        self.assertTrue(is_void_for_betting(status, None))

    def test_slip_pool_eligibility(self):
        self.assertTrue(is_eligible_for_slip_pool("upcoming"))
        self.assertFalse(is_eligible_for_slip_pool("cancelled"))
        self.assertFalse(is_eligible_for_slip_pool("postponed"))
        self.assertFalse(is_eligible_for_slip_pool("abandoned"))
        self.assertFalse(is_eligible_for_slip_pool("unknown"))
        self.assertFalse(is_eligible_for_slip_pool("started"))
        self.assertFalse(is_eligible_for_slip_pool("completed"))
        self.assertTrue(
            is_eligible_for_slip_pool("completed", include_completed=True)
        )
        self.assertFalse(
            is_eligible_for_slip_pool("cancelled", include_completed=True)
        )

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

    def test_retired_without_winner_voidable(self):
        status = classify_match_lifecycle(event_status="Retired")
        self.assertEqual(status, "retired")
        self.assertTrue(is_void_for_betting(status, None))

    def test_unmapped_status_stays_upcoming_non_void(self):
        status = classify_match_lifecycle(event_status="SomeWeirdFlag")
        self.assertEqual(status, "upcoming")
        self.assertFalse(is_void_for_betting(status, None))

    def test_legacy_aliases_normalize(self):
        self.assertEqual(normalize_lifecycle_status("scheduled"), "upcoming")
        self.assertEqual(normalize_lifecycle_status("live"), "started")
        self.assertEqual(normalize_lifecycle_status("finished"), "completed")
        self.assertEqual(normalize_lifecycle_status("unknown_problem"), "unknown")


class SettlementPolicyMatrixTest(unittest.TestCase):
    """Every lifecycle status: singles, slips, stake, profit/ROI, void_odds."""

    def test_policy_for_every_status_without_winner(self):
        expected = {
            "upcoming": ("pending", True, False, False),
            "started": ("pending", True, False, False),
            "completed": ("void", False, False, False),
            "postponed": ("pending", True, False, False),
            "cancelled": ("void", False, False, False),
            "retired": ("void", False, False, False),
            "walkover": ("void", False, False, False),
            "abandoned": ("void", False, False, False),
            "unknown": ("void", False, False, False),
        }
        for status in ALL_STATUSES:
            policy = settlement_policy(status, actual_winner=None, predicted_winner="First Player")
            outcome, stake_at_risk, include_roi, counts_loss = expected[status]
            self.assertEqual(policy.singles_outcome, outcome, status)
            self.assertEqual(policy.slip_pick_outcome, outcome, status)
            self.assertEqual(policy.stake_at_risk, stake_at_risk, status)
            self.assertEqual(policy.include_in_profit_roi, include_roi, status)
            self.assertEqual(policy.counts_as_loss, counts_loss, status)
            self.assertFalse(policy.void_odds_affected, status)

    def test_settle_each_status_idempotent(self):
        cases = [
            ("upcoming", None, "pending", 0.0, 0.0, False),
            ("started", None, "pending", 0.0, 0.0, False),
            ("postponed", None, "pending", 0.0, 0.0, False),
            ("cancelled", None, "void", 0.0, 0.0, False),
            ("abandoned", None, "void", 0.0, 0.0, False),
            ("unknown", None, "void", 0.0, 0.0, False),
            ("walkover", None, "void", 0.0, 0.0, False),
            ("retired", None, "void", 0.0, 0.0, False),
            ("completed", "First Player", "won", 1.0, 0.5, True),
            ("walkover", "First Player", "won", 1.0, 0.5, True),
            ("retired", "Second Player", "lost", 1.0, -1.0, True),
            ("completed", "Second Player", "lost", 1.0, -1.0, True),
        ]
        for lifecycle, winner, outcome, stake, profit, include in cases:
            first = settle_simulated_bet(
                lifecycle=lifecycle,
                predicted_winner="First Player",
                actual_winner=winner,
                market_odds=1.5,
            )
            second = settle_simulated_bet(
                lifecycle=lifecycle,
                predicted_winner="First Player",
                actual_winner=winner,
                market_odds=1.5,
            )
            self.assertEqual(first, second, lifecycle)
            self.assertEqual(first.outcome, outcome, lifecycle)
            self.assertEqual(first.stake_units, stake, lifecycle)
            self.assertAlmostEqual(first.profit_units, profit, places=6, msg=lifecycle)
            self.assertEqual(first.include_in_roi, include, lifecycle)
            if outcome == "void":
                self.assertIsNotNone(first.void_reason)
                self.assertNotEqual(first.outcome, "lost")

    def test_cancelled_never_counts_as_loss_for_singles_or_slips(self):
        for status in ("cancelled", "abandoned", "unknown"):
            settlement = settle_simulated_bet(
                lifecycle=status,
                predicted_winner="First Player",
                actual_winner=None,
                market_odds=2.0,
            )
            self.assertEqual(settlement.outcome, "void")
            self.assertEqual(settlement.profit_units, 0.0)
            self.assertFalse(settlement.include_in_roi)
            policy = settlement_policy(status)
            self.assertFalse(policy.counts_as_loss)
            self.assertEqual(policy.singles_outcome, "void")
            self.assertEqual(policy.slip_pick_outcome, "void")

    def test_void_odds_never_affected_by_lifecycle(self):
        for status in ALL_STATUSES:
            policy = settlement_policy(
                status,
                actual_winner="First Player" if status in {"completed", "walkover", "retired"} else None,
                predicted_winner="First Player",
            )
            self.assertFalse(policy.void_odds_affected, status)


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

    def test_pick_void_when_postponed_for_slip_context(self):
        self.assertEqual(
            _resolve_pick_status(self._pick(), None, match_lifecycle_status="postponed"),
            ("void", None),
        )

    def test_pick_pending_when_upcoming_and_started(self):
        self.assertEqual(
            _resolve_pick_status(self._pick(), None, match_lifecycle_status="upcoming"),
            ("pending", None),
        )
        self.assertEqual(
            _resolve_pick_status(self._pick(), None, match_lifecycle_status="started"),
            ("pending", None),
        )

    def test_legacy_status_still_voids(self):
        self.assertEqual(
            _resolve_pick_status(self._pick(), None, match_lifecycle_status="unknown_problem"),
            ("void", None),
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
        self.assertEqual(resolve_slip_status_from_picks(["won", "void", "won"]), "won")

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
        self.assertEqual(
            slip_profit_units(slip_status="won", stake=10.0, effective_combined_odds=3.0),
            20.0,
        )

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
