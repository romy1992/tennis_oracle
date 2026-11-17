"""Data-sufficiency assessment for a single pre-match prediction.

Purely descriptive: it never changes a probability. It tells API consumers how
much real evidence stands behind a prediction, so missing inputs are not
presented as if they were known.

Thresholds come from the offline walk-forward benchmark
(``backend/data/reports/benchmarks/match_winner_walk_forward_benchmark.json``,
segments ``min_prior_matches`` and ``bookmaker_count``):
- below ``LOW_HISTORY_MATCHES`` prior matches the history-only contenders
  (Elo, no-odds models) lose most of their accuracy, i.e. form/Elo/H2H
  features carry little independent information and the prediction rests on
  the market odds alone;
- with at most ``FEW_BOOKMAKERS`` bookmakers the average quote is noisier.
In the same benchmark the odds-aware model was not worse than the market in
those segments, which is why the status is exposed and predictions are not
withheld.
"""

from __future__ import annotations

from typing import Any

STATUS_SUFFICIENT = "sufficient"
STATUS_LIMITED = "limited"
STATUS_INSUFFICIENT = "insufficient"

LOW_HISTORY_MATCHES = 5
FEW_BOOKMAKERS = 3

# Reasons that make a prediction impossible or not based on real inputs.
_BLOCKING_REASONS = frozenset({"missing_player_keys_or_date", "missing_odds"})


def assess_data_sufficiency(
    *,
    player_1_prior_matches: int | None = None,
    player_2_prior_matches: int | None = None,
    surface_known: bool | None = None,
    ranking_available: bool | None = None,
    odds_available: bool | None = None,
    bookmaker_count: int | None = None,
    unavailable_feature_columns: list[str] | None = None,
    blocking_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Return ``{"status", "reasons", "systemic_gaps", "details"}``.

    ``None`` means "not evaluated here": it is reported in ``details`` and
    never counted as a problem nor as a confirmation.

    ``reasons`` are specific to this match and drive ``status``.
    ``systemic_gaps`` are inputs the serving pipeline lacks for (almost) every
    match (no ranking source, enrichment columns never built): they are
    reported for transparency but do not downgrade the status, otherwise every
    prediction would be "limited" and the status would carry no information.
    """
    reasons: list[str] = []
    systemic_gaps: list[str] = []
    blocking = [reason for reason in (blocking_reasons or []) if reason in _BLOCKING_REASONS]
    reasons.extend(blocking)
    if odds_available is False and "missing_odds" not in reasons:
        reasons.append("missing_odds")
        blocking.append("missing_odds")

    for side, prior in (("player_1", player_1_prior_matches), ("player_2", player_2_prior_matches)):
        if prior is None:
            continue
        if prior <= 0:
            reasons.append(f"{side}_no_history")
        elif prior < LOW_HISTORY_MATCHES:
            reasons.append(f"{side}_low_history")
    if surface_known is False:
        reasons.append("surface_unknown")
    if bookmaker_count is not None and 0 < bookmaker_count <= FEW_BOOKMAKERS:
        reasons.append("few_bookmakers")
    if ranking_available is False:
        systemic_gaps.append("ranking_unavailable")
    if unavailable_feature_columns:
        systemic_gaps.append("enrichment_features_unavailable")

    if blocking:
        status = STATUS_INSUFFICIENT
    elif reasons:
        status = STATUS_LIMITED
    else:
        status = STATUS_SUFFICIENT

    return {
        "status": status,
        "reasons": reasons,
        "systemic_gaps": systemic_gaps,
        "details": {
            "player_1_prior_matches": player_1_prior_matches,
            "player_2_prior_matches": player_2_prior_matches,
            "surface_known": surface_known,
            "ranking_available": ranking_available,
            "bookmaker_count": bookmaker_count,
            "unavailable_feature_columns": list(unavailable_feature_columns or []),
            "low_history_threshold": LOW_HISTORY_MATCHES,
            "few_bookmakers_threshold": FEW_BOOKMAKERS,
        },
    }
