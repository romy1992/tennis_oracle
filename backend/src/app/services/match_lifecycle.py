"""Centralized match + simulated-bet lifecycle.

Normalizes API-Tennis status fields and defines how each lifecycle state
affects singles, betting slips, stake, profit, ROI stats, and ``void_odds``.

Naming note: match/pick *void* (annullamento scommessa) is unrelated to
``void_odds`` (fair/break-even odds from model probability ``1/P``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

COMPLETED_WINNERS = ("First Player", "Second Player")

MatchLifecycleStatus = Literal[
    "upcoming",
    "started",
    "completed",
    "postponed",
    "cancelled",
    "retired",
    "walkover",
    "abandoned",
    "unknown",
]

BetOutcome = Literal["pending", "won", "lost", "void"]

MATCH_LIFECYCLE_LABELS_IT: dict[MatchLifecycleStatus, str] = {
    "upcoming": "Da giocare",
    "started": "In corso",
    "completed": "Terminata",
    "postponed": "Rinviata",
    "cancelled": "Annullata",
    "retired": "Ritiro",
    "walkover": "Walkover",
    "abandoned": "Abbandonata",
    "unknown": "Problema / esito mancante",
}

# Legacy API values still accepted by normalize helpers / callers.
_LEGACY_LIFECYCLE_ALIASES: dict[str, MatchLifecycleStatus] = {
    "scheduled": "upcoming",
    "live": "started",
    "finished": "completed",
    "unknown_problem": "unknown",
}

# Terminal non-bettable when there is no COMPLETED_WINNERS winner.
_VOID_LIFECYCLE_WITHOUT_WINNER: frozenset[MatchLifecycleStatus] = frozenset(
    {
        "cancelled",
        "abandoned",
        "unknown",
        "walkover",
        "retired",
        "completed",  # completed without winner (defensive; classify maps this to unknown)
    }
)

_TERMINAL_LIFECYCLES: frozenset[MatchLifecycleStatus] = frozenset(
    {
        "completed",
        "cancelled",
        "abandoned",
        "walkover",
        "retired",
        "unknown",
    }
)

# Status that must not enter newly generated / regenerated betting slips
# (or live PLAY publication that reuses the same candidate pool) once known.
_SLIP_POOL_EXCLUDED_LIFECYCLES: frozenset[MatchLifecycleStatus] = frozenset(
    {
        "cancelled",
        "postponed",
        "abandoned",
        "unknown",
        "started",
    }
)

_CANCELLED_TOKENS = (
    "cancel",
    "deleted",
    "scratch",
    "not played",
    "not_played",
    "no play",
    "called off",
)
_ABANDONED_TOKENS = ("abandon", "washed out", "washed_out")
_POSTPONED_TOKENS = (
    "postpon",
    "delay",
    "suspend",
    "interrupt",
    "rinviat",
    "to be fixed",
    "tbf",
)
_WALKOVER_TOKENS = ("walkover", "walk over", "w/o", "wo ", " wo")
_RETIRED_TOKENS = ("retir", "default", "disqual")
_FINISHED_TOKENS = ("finish", "complet", "ended", "closed", "ft", "full time")
_LIVE_TOKENS = ("live", "in progress", "in_progress", "started", "playing")
_LIVE_SET_RE = re.compile(r"\bset\s*[1-5]\b", re.IGNORECASE)
# "started" in _LIVE_TOKENS is a bare substring match, so the standard
# API-Tennis status for every not-yet-played fixture ("Not Started") would
# otherwise be misclassified as the live "started" lifecycle. Must be
# checked before the live-token check below.
_NOT_STARTED_RE = re.compile(r"\bnot\s+started\b", re.IGNORECASE)

_UNMAPPED_LOGGED: set[str] = set()


@dataclass(frozen=True)
class LifecycleSettlementPolicy:
    """How a lifecycle state affects simulated bets and reporting.

    ``void_odds_affected`` is always False: fair odds are a model concept,
    independent of match completion.
    """

    lifecycle: MatchLifecycleStatus
    singles_outcome: BetOutcome
    slip_pick_outcome: BetOutcome
    stake_at_risk: bool
    include_in_profit_roi: bool
    counts_as_loss: bool
    void_odds_affected: bool
    notes: str


@dataclass(frozen=True)
class SimulatedBetSettlement:
    """Idempotent settlement result for one simulated single/pick."""

    outcome: BetOutcome
    is_correct: bool | None
    lifecycle: MatchLifecycleStatus
    stake_units: float
    profit_units: float
    include_in_roi: bool
    void_reason: str | None = None


def match_lifecycle_label(status: MatchLifecycleStatus | str) -> str:
    normalized = normalize_lifecycle_status(status)
    return MATCH_LIFECYCLE_LABELS_IT[normalized]


def normalize_lifecycle_status(status: MatchLifecycleStatus | str) -> MatchLifecycleStatus:
    """Accept current and legacy lifecycle codes."""
    key = str(status).strip().lower()
    if key in _LEGACY_LIFECYCLE_ALIASES:
        return _LEGACY_LIFECYCLE_ALIASES[key]
    if key in MATCH_LIFECYCLE_LABELS_IT:
        return key  # type: ignore[return-value]
    raise ValueError(f"Unknown match lifecycle status: {status!r}")


def is_terminal_lifecycle(lifecycle: MatchLifecycleStatus | str) -> bool:
    return normalize_lifecycle_status(lifecycle) in _TERMINAL_LIFECYCLES


def is_void_for_betting(
    lifecycle: MatchLifecycleStatus | str,
    actual_winner: str | None,
) -> bool:
    """True when the simulated bet should be voided (not lost)."""
    if actual_winner in COMPLETED_WINNERS:
        return False
    return normalize_lifecycle_status(lifecycle) in _VOID_LIFECYCLE_WITHOUT_WINNER


def settlement_policy(
    lifecycle: MatchLifecycleStatus | str,
    *,
    actual_winner: str | None = None,
    predicted_winner: str | None = None,
    has_result: bool | None = None,
    postponed_as_void: bool = False,
) -> LifecycleSettlementPolicy:
    """Explicit impact matrix for a lifecycle (+ optional winner context).

    ``has_result`` lets callers settle markets whose "winner" is not a player
    name (e.g. Over/Under games: "Over"/"Under") by overriding the default
    ``actual_winner in COMPLETED_WINNERS`` check. ``None`` (default) preserves
    the original match-winner behaviour.
    """
    status = normalize_lifecycle_status(lifecycle)
    has_winner = has_result if has_result is not None else actual_winner in COMPLETED_WINNERS

    if has_winner:
        won = predicted_winner is not None and predicted_winner == actual_winner
        if predicted_winner is None:
            outcome: BetOutcome = "pending"
        elif won:
            outcome = "won"
        else:
            outcome = "lost"
        return LifecycleSettlementPolicy(
            lifecycle=status,
            singles_outcome=outcome,
            slip_pick_outcome=outcome,
            stake_at_risk=outcome == "pending",
            include_in_profit_roi=outcome in {"won", "lost"},
            counts_as_loss=outcome == "lost",
            void_odds_affected=False,
            notes=(
                "Winner known: settle won/lost for completed/walkover/retired/etc. "
                "Quota void (break-even) unchanged."
            ),
        )

    if status == "postponed" and postponed_as_void:
        return LifecycleSettlementPolicy(
            lifecycle=status,
            singles_outcome="void",
            slip_pick_outcome="void",
            stake_at_risk=False,
            include_in_profit_roi=False,
            counts_as_loss=False,
            void_odds_affected=False,
            notes="Postponed pre-start slip leg: void and stake refunded.",
        )

    if status in {"upcoming", "started", "postponed"}:
        return LifecycleSettlementPolicy(
            lifecycle=status,
            singles_outcome="pending",
            slip_pick_outcome="pending",
            stake_at_risk=True,
            include_in_profit_roi=False,
            counts_as_loss=False,
            void_odds_affected=False,
            notes=(
                "Match not settled yet. Stake remains open; no profit/ROI contribution. "
                "Postponed stays pending (not void)."
            ),
        )

    if status in _VOID_LIFECYCLE_WITHOUT_WINNER:
        return LifecycleSettlementPolicy(
            lifecycle=status,
            singles_outcome="void",
            slip_pick_outcome="void",
            stake_at_risk=False,
            include_in_profit_roi=False,
            counts_as_loss=False,
            void_odds_affected=False,
            notes=(
                "Cancelled / not playable without bettable winner: void, never lost. "
                "Stake refunded (0 in ROI denominator); profit 0."
            ),
        )

    # Defensive fallback — should not be reached for known statuses.
    return LifecycleSettlementPolicy(
        lifecycle=status,
        singles_outcome="pending",
        slip_pick_outcome="pending",
        stake_at_risk=True,
        include_in_profit_roi=False,
        counts_as_loss=False,
        void_odds_affected=False,
        notes="Fallback pending; do not treat as loss.",
    )


def settle_simulated_bet(
    *,
    lifecycle: MatchLifecycleStatus | str,
    predicted_winner: str | None,
    actual_winner: str | None,
    market_odds: float | None = None,
    stake_units: float = 1.0,
    has_result: bool | None = None,
    postponed_as_void: bool = False,
) -> SimulatedBetSettlement:
    """Idempotent settlement for one simulated single or slip pick.

    Repeated calls with the same inputs always yield the same result.
    Cancelled / non-played matches never count as losses. ``has_result``
    forwards to :func:`settlement_policy` for non-player-name markets
    (Over/Under, etc.).
    """
    status = normalize_lifecycle_status(lifecycle)
    policy = settlement_policy(
        status,
        actual_winner=actual_winner,
        predicted_winner=predicted_winner,
        has_result=has_result,
        postponed_as_void=postponed_as_void,
    )
    outcome = policy.slip_pick_outcome
    is_correct: bool | None
    if outcome == "won":
        is_correct = True
    elif outcome == "lost":
        is_correct = False
    else:
        is_correct = None

    if outcome == "won":
        odd = float(market_odds) if market_odds is not None else 1.0
        profit = stake_units * (odd - 1.0)
        stake = stake_units
    elif outcome == "lost":
        profit = -stake_units
        stake = stake_units
    else:
        # pending / void: no realized P/L; void stake excluded from ROI denom
        profit = 0.0
        stake = 0.0

    void_reason = match_lifecycle_label(status) if outcome == "void" else None
    return SimulatedBetSettlement(
        outcome=outcome,
        is_correct=is_correct,
        lifecycle=status,
        stake_units=stake,
        profit_units=profit,
        include_in_roi=policy.include_in_profit_roi,
        void_reason=void_reason,
    )


def resolve_slip_status_from_picks(pick_outcomes: list[BetOutcome]) -> BetOutcome:
    """Aggregate slip status from pick outcomes (void legs ignored for win/loss)."""
    active = [status for status in pick_outcomes if status != "void"]
    if not active:
        return "void"
    if any(status == "lost" for status in active):
        return "lost"
    if all(status == "won" for status in active):
        return "won"
    return "pending"


def slip_profit_units(
    *,
    slip_status: BetOutcome,
    stake: float,
    effective_combined_odds: float | None,
) -> float:
    """Realized slip profit; void/pending → 0 (stake refunded / still open)."""
    if slip_status == "won":
        odds = effective_combined_odds if effective_combined_odds is not None else 1.0
        return stake * odds - stake
    if slip_status == "lost":
        return -stake
    return 0.0


def _normalize_status(event_status: str | None) -> str:
    if not event_status:
        return ""
    return " ".join(str(event_status).strip().lower().split())


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _is_live_flag(event_live: str | None) -> bool:
    if event_live is None:
        return False
    return str(event_live).strip().lower() in {"1", "true", "yes", "y", "live"}


def is_eligible_for_slip_pool(
    lifecycle: MatchLifecycleStatus,
    *,
    include_completed: bool = False,
) -> bool:
    """Whether a fixture may enter newly built slip candidate pools.

    Excludes cancelled / postponed / abandoned / unknown (missing or error
    outcome) and already-started matches. Live generation (``include_completed=
    False``) additionally requires ``upcoming`` only. Historical replay may
    keep completed / walkover / retired rows.
    """
    if lifecycle in _SLIP_POOL_EXCLUDED_LIFECYCLES:
        return False
    if include_completed:
        return True
    return lifecycle == "upcoming"


def classify_match_lifecycle(
    *,
    event_status: str | None = None,
    event_winner: str | None = None,
    event_final_result: str | None = None,
    event_live: str | None = None,
    is_completed: bool | None = None,
) -> MatchLifecycleStatus:
    """Map raw API fields to a normalized lifecycle status.

    Rules:
    - Winner in COMPLETED_WINNERS → completed / walkover / retired (settleable).
    - cancelled / abandoned / finished-without-winner → void candidates.
    - postponed / delayed / suspended → postponed (non-terminal; pick stays pending).
    - Unrecognized status without winner → upcoming (conservative; do not void).
    """
    status = _normalize_status(event_status)
    has_winner = event_winner in COMPLETED_WINNERS
    result = (event_final_result or "").strip()
    has_result = bool(result and result != "-")

    if has_winner:
        if _contains_any(status, _WALKOVER_TOKENS):
            return "walkover"
        if _contains_any(status, _RETIRED_TOKENS):
            return "retired"
        return "completed"

    if _contains_any(status, _CANCELLED_TOKENS):
        return "cancelled"
    if _contains_any(status, _ABANDONED_TOKENS):
        return "abandoned"
    if _contains_any(status, _WALKOVER_TOKENS):
        return "walkover"
    if _contains_any(status, _RETIRED_TOKENS):
        return "retired"
    if _contains_any(status, _POSTPONED_TOKENS):
        return "postponed"

    not_started = bool(_NOT_STARTED_RE.search(status))
    if (
        _is_live_flag(event_live)
        or (_contains_any(status, _LIVE_TOKENS) and not not_started)
        or _LIVE_SET_RE.search(status)
    ):
        return "started"

    if _contains_any(status, _FINISHED_TOKENS) or is_completed is True or has_result:
        # Finished-like signal but no bettable winner → problem / void candidate.
        # This check intentionally follows live detection because API-Tennis
        # exposes a partial ``event_final_result`` (for example ``1 - 0``)
        # while a later set is still being played.
        return "unknown"
    if not_started:
        return "upcoming"

    if status and status not in {"", "-", "null", "none"}:
        if status not in _UNMAPPED_LOGGED:
            _UNMAPPED_LOGGED.add(status)
            logger.info("Unmapped event_status=%r; treating as upcoming (non-void)", event_status)
        return "upcoming"

    return "upcoming"
