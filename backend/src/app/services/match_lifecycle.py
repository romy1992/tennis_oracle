"""Normalize API-Tennis match status for UI and betting-slip void settlement.

Naming note: this module is about match/pick *voiding* (annullamento scommessa).
It is unrelated to ``void_odds`` (fair/break-even odds from model probability).
"""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

COMPLETED_WINNERS = ("First Player", "Second Player")

MatchLifecycleStatus = Literal[
    "scheduled",
    "live",
    "finished",
    "postponed",
    "cancelled",
    "abandoned",
    "walkover",
    "retired",
    "unknown_problem",
]

MATCH_LIFECYCLE_LABELS_IT: dict[MatchLifecycleStatus, str] = {
    "scheduled": "Da giocare",
    "live": "In corso",
    "finished": "Terminata",
    "postponed": "Rinviata",
    "cancelled": "Annullata",
    "abandoned": "Abbandonata",
    "walkover": "Walkover",
    "retired": "Ritiro",
    "unknown_problem": "Problema / esito mancante",
}

# Terminal non-bettable when there is no COMPLETED_WINNERS winner.
_VOID_LIFECYCLE_WITHOUT_WINNER: frozenset[MatchLifecycleStatus] = frozenset(
    {
        "cancelled",
        "abandoned",
        "unknown_problem",
        "walkover",
        "retired",
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

_UNMAPPED_LOGGED: set[str] = set()


def match_lifecycle_label(status: MatchLifecycleStatus) -> str:
    return MATCH_LIFECYCLE_LABELS_IT[status]


def is_void_for_betting(
    lifecycle: MatchLifecycleStatus,
    actual_winner: str | None,
) -> bool:
    """True when the pick should be voided (excluded from combined odds)."""
    if actual_winner in COMPLETED_WINNERS:
        return False
    return lifecycle in _VOID_LIFECYCLE_WITHOUT_WINNER


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
    - Winner in COMPLETED_WINNERS → finished / walkover / retired (settleable).
    - cancelled / abandoned / finished-without-winner → terminal problem statuses.
    - postponed / delayed / suspended → postponed (non-terminal; pick stays pending).
    - Unrecognized status without winner → scheduled (conservative; do not void).
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
        return "finished"

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

    if _contains_any(status, _FINISHED_TOKENS) or is_completed is True or has_result:
        # Finished-like signal but no bettable winner → problem / void candidate.
        return "unknown_problem"

    if _is_live_flag(event_live) or _contains_any(status, _LIVE_TOKENS) or _LIVE_SET_RE.search(status):
        return "live"

    if status and status not in {"", "-", "null", "none"}:
        if status not in _UNMAPPED_LOGGED:
            _UNMAPPED_LOGGED.add(status)
            logger.info("Unmapped event_status=%r; treating as scheduled (non-void)", event_status)
        return "scheduled"

    return "scheduled"
