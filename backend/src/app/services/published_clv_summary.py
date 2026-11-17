"""Read-only CLV (closing line value) report of the published-prediction ledger.

Reuses ``settle_published_tips`` (same per-tip CLV as ``/published-predictions/stats``
and the live-beta dashboard) and only regroups it by market and by
``value_decision``, adding medians, the no-vig variant and why CLV is missing.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import median

from sqlalchemy.orm import Session

from backend.src.app.schemas.published_prediction import (
    PublishedClvBucket,
    PublishedClvSummary,
)
from backend.src.app.services.live_betting_metrics import average, round_metric
from backend.src.app.services.published_live_stats import (
    CLV_MISSING_AWAITING_CLOSING,
    CLV_MISSING_NO_PUBLISHED_ODDS,
    CLV_MISSING_REASONS,
    _SettledTip,
    settle_published_tips,
)

CLV_FORMULA = (
    "clv_pct = (quota_presa / quota_closing - 1) * 100. quota_presa = quota pubblicata "
    "della tip (media tra bookmaker al momento della pubblicazione); quota_closing = "
    "stesso bookmaker se lo snapshot di pubblicazione ne indica uno reale, altrimenti "
    "media delle quote dei bookmaker nell'ultima cattura closing valida, stesso "
    "mercato/linea/selezione."
)
CLV_NO_VIG_FORMULA = (
    "clv_no_vig_pct = (quota_presa * p_closing_no_vig - 1) * 100, con "
    "p_closing_no_vig = (1/q_sel) / (1/q_sel + 1/q_opposta) sulle quote closing "
    "(medie per consensus_avg): rendimento atteso della quota presa se la closing "
    "senza margine e' la probabilita' vera."
)
CLOSING_RULES = [
    "Valida solo una closing catturata dopo published_at (al secondo) e non oltre "
    "il kickoff programmato (event_date/event_time Europe/Rome).",
    "Stesso mercato, stessa linea O/U e stessa selezione della tip; tra le closing "
    "valide vale l'ultima cattura.",
    "CLV > 0: la quota presa era migliore della closing (il mercato si e' mosso "
    "verso la tip), indipendentemente dall'esito.",
]

MARKET_LABELS: dict[str, str] = {
    "match_winner": "Vincente match",
    "first_set_winner": "Vincente 1° set",
    "over_under_games": "Over/Under game",
}
DECISION_ORDER: tuple[str, ...] = ("PLAY", "BORDERLINE", "NO BET", "none")
DECISION_LABELS: dict[str, str] = {
    "PLAY": "PLAY",
    "BORDERLINE": "BORDERLINE",
    "NO BET": "NO BET",
    "none": "Senza decisione",
}


def _pct(part: int, total: int) -> float | None:
    return round_metric((part / total * 100.0) if total else None, 4)


def _bucket(tips: list[_SettledTip], *, key: str, label: str) -> PublishedClvBucket:
    clv_values = [tip.clv.clv_pct for tip in tips if tip.clv.clv_pct is not None]
    no_vig_values = [
        tip.clv.clv_no_vig_pct for tip in tips if tip.clv.clv_no_vig_pct is not None
    ]
    missing_reasons: dict[str, int] = {}
    for reason in CLV_MISSING_REASONS:
        count = sum(1 for tip in tips if tip.clv.missing_reason == reason)
        if count:
            missing_reasons[reason] = count
    basis_counts: dict[str, int] = defaultdict(int)
    for tip in tips:
        if tip.clv.clv_pct is not None and tip.clv.closing_basis:
            basis_counts[tip.clv.closing_basis] += 1
    clv_count = len(clv_values)
    positive = sum(1 for value in clv_values if value > 0)
    no_vig_positive = sum(1 for value in no_vig_values if value > 0)
    eligible = len(tips) - missing_reasons.get(
        CLV_MISSING_AWAITING_CLOSING, 0
    ) - missing_reasons.get(CLV_MISSING_NO_PUBLISHED_ODDS, 0)
    return PublishedClvBucket(
        key=key,
        label=label,
        predictions_total=len(tips),
        clv_count=clv_count,
        clv_missing=len(tips) - clv_count,
        clv_coverage_pct=_pct(clv_count, len(tips)),
        clv_eligible=eligible,
        clv_coverage_eligible_pct=_pct(clv_count, eligible),
        clv_avg_pct=round_metric(average(clv_values), 4),
        clv_median_pct=round_metric(median(clv_values) if clv_values else None, 4),
        clv_positive_count=positive,
        clv_positive_pct=_pct(positive, clv_count),
        clv_no_vig_count=len(no_vig_values),
        clv_no_vig_avg_pct=round_metric(average(no_vig_values), 4),
        clv_no_vig_median_pct=round_metric(
            median(no_vig_values) if no_vig_values else None, 4
        ),
        clv_no_vig_positive_pct=_pct(no_vig_positive, len(no_vig_values)),
        closing_basis_counts=dict(basis_counts),
        missing_reasons=missing_reasons,
    )


def _decision_key(tip: _SettledTip) -> str:
    return tip.tip.value_decision or "none"


def _ordered_keys(present: set[str], order: tuple[str, ...]) -> list[str]:
    known = [key for key in order if key in present]
    return known + sorted(present - set(order))


def compute_published_clv_summary(
    db: Session,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    event_date_from: date | None = None,
    event_date_to: date | None = None,
    model_version: str | None = None,
    model_name: str | None = None,
    publication_source: str | None = None,
    tournament_name: str | None = None,
    surface: str | None = None,
    odds_band: str | None = None,
    latest_only: bool = True,
    market: str | None = None,
    include_archived: bool = True,
    official_only: bool = False,
    initial_status: str | None = None,
) -> PublishedClvSummary:
    settled = settle_published_tips(
        db,
        from_date=from_date,
        to_date=to_date,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        model_version=model_version,
        model_name=model_name,
        publication_source=publication_source,
        tournament_name=tournament_name,
        surface=surface,
        odds_band=odds_band,
        latest_only=latest_only,
        market=market,
        include_archived=include_archived,
        official_only=official_only,
        initial_status=initial_status,
    )

    by_market: dict[str, list[_SettledTip]] = defaultdict(list)
    by_decision: dict[str, list[_SettledTip]] = defaultdict(list)
    by_market_decision: dict[tuple[str, str], list[_SettledTip]] = defaultdict(list)
    for tip in settled:
        market_key = tip.tip.market or "match_winner"
        decision_key = _decision_key(tip)
        by_market[market_key].append(tip)
        by_decision[decision_key].append(tip)
        by_market_decision[(market_key, decision_key)].append(tip)

    market_order = tuple(MARKET_LABELS.keys())
    market_keys = _ordered_keys(set(by_market), market_order)
    decision_keys = _ordered_keys(set(by_decision), DECISION_ORDER)

    market_decision_buckets: list[PublishedClvBucket] = []
    for market_key in market_keys:
        for decision_key in _ordered_keys(
            {decision for (mk, decision) in by_market_decision if mk == market_key},
            DECISION_ORDER,
        ):
            market_decision_buckets.append(
                _bucket(
                    by_market_decision[(market_key, decision_key)],
                    key=f"{market_key}|{decision_key}",
                    label=(
                        f"{MARKET_LABELS.get(market_key, market_key)} / "
                        f"{DECISION_LABELS.get(decision_key, decision_key)}"
                    ),
                )
            )

    return PublishedClvSummary(
        clv_formula=CLV_FORMULA,
        clv_no_vig_formula=CLV_NO_VIG_FORMULA,
        closing_rules=list(CLOSING_RULES),
        latest_only=latest_only,
        from_date=from_date,
        to_date=to_date,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        model_version=model_version,
        model_name=model_name,
        publication_source=publication_source,
        market=market,
        include_archived=include_archived,
        official_only=official_only,
        overall=_bucket(settled, key="all", label="Tutte"),
        by_market=[
            _bucket(by_market[key], key=key, label=MARKET_LABELS.get(key, key))
            for key in market_keys
        ],
        by_decision=[
            _bucket(by_decision[key], key=key, label=DECISION_LABELS.get(key, key))
            for key in decision_keys
        ],
        by_market_decision=market_decision_buckets,
    )
