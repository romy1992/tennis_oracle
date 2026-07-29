"""Live statistics for the immutable published-prediction tipbook.

Source of truth: ``PublishedPrediction`` (latest version per publication by default).
Settlement is computed at read time via fixture lifecycle + ``settle_simulated_bet``.
Does not use training/backtest metrics (``value_bet_metrics``) or mutable
``MatchPrediction`` / ``BettingSlip`` aggregates.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.src.app.schemas.published_prediction import (
    OddsBand,
    PublishedLiveStatsBucket,
    PublishedLiveStatsSummary,
    PublishedSettledTipRead,
)
from backend.src.app.services.live_betting_metrics import (
    average,
    hit_rate_pct,
    longest_streaks,
    max_drawdown,
    roi_pct,
    round_metric,
    yield_pct,
)
from backend.src.app.services.match_lifecycle import (
    COMPLETED_WINNERS,
    BetOutcome,
    classify_match_lifecycle,
    settle_simulated_bet,
)
from backend.src.entity.fixture import Fixture
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot
from backend.src.entity.published_prediction import PublishedPrediction
from backend.src.entity.tournaments import Tournament

OddsBucket = OddsBand
EdgeBucket = Literal["lt_0", "0_5", "5_10", "gte_10", "missing"]

ODDS_BUCKET_LABELS: dict[str, str] = {
    "lt_1_50": "< 1.50",
    "1_50_2_00": "1.50 – 2.00",
    "2_00_3_00": "2.00 – 3.00",
    "gte_3_00": "≥ 3.00",
    "missing": "Senza quota",
}

VALID_ODDS_BANDS: frozenset[str] = frozenset(ODDS_BUCKET_LABELS.keys())

EDGE_BUCKET_LABELS: dict[str, str] = {
    "lt_0": "< 0%",
    "0_5": "0% – 5%",
    "5_10": "5% – 10%",
    "gte_10": "≥ 10%",
    "missing": "Senza edge",
}


@dataclass(frozen=True)
class _MatchContext:
    lifecycle: str
    actual_winner: str | None
    player_1_name: str | None
    player_2_name: str | None
    surface: str | None
    event_date: date | None


@dataclass
class _SettledTip:
    tip: PublishedPrediction
    outcome: BetOutcome
    profit: float
    stake_settled: float
    surface: str | None
    lifecycle: str
    clv: "_TipClv"
    sort_date: date
    sort_ts: datetime


@dataclass(frozen=True)
class _TipClv:
    publication_odds: float | None = None
    publication_bookmaker: str | None = None
    closing_odds: float | None = None
    closing_bookmaker: str | None = None
    no_vig_publication_prob: float | None = None
    no_vig_closing_prob: float | None = None
    clv_pct: float | None = None
    clv_prob_delta_pct: float | None = None


def _normalize_name(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def selection_to_predicted_winner(
    selection: str,
    player_1_name: str | None,
    player_2_name: str | None,
) -> str | None:
    """Map published selection (name or side code) to First/Second Player."""
    raw = selection.strip()
    key = _normalize_name(raw)
    if key in {"first player", "1", "home", "p1"}:
        return "First Player"
    if key in {"second player", "2", "away", "p2"}:
        return "Second Player"

    p1 = _normalize_name(player_1_name)
    p2 = _normalize_name(player_2_name)
    if p1 and key == p1:
        return "First Player"
    if p2 and key == p2:
        return "Second Player"
    if p1 and (key in p1 or p1 in key):
        return "First Player"
    if p2 and (key in p2 or p2 in key):
        return "Second Player"
    return None


def odds_bucket(odds: float | None) -> OddsBucket:
    if odds is None:
        return "missing"
    if odds < 1.5:
        return "lt_1_50"
    if odds < 2.0:
        return "1_50_2_00"
    if odds < 3.0:
        return "2_00_3_00"
    return "gte_3_00"


def edge_bucket(edge: float | None) -> EdgeBucket:
    """Edge is stored as percentage points on the ledger (e.g. 14.7 = 14.7%)."""
    if edge is None:
        return "missing"
    if edge < 0:
        return "lt_0"
    if edge < 5:
        return "0_5"
    if edge < 10:
        return "5_10"
    return "gte_10"


def period_key(event_date: date | None, published_at: datetime) -> str:
    ref = event_date or published_at.date()
    return f"{ref.year:04d}-{ref.month:02d}"


def _load_match_contexts(db: Session, event_keys: list[int]) -> dict[int, _MatchContext]:
    if not event_keys:
        return {}

    fixtures = list(
        db.scalars(select(Fixture).where(Fixture.event_key.in_(event_keys))).all()
    )
    next_rows = list(
        db.scalars(select(NextFixture).where(NextFixture.event_key.in_(event_keys))).all()
    )
    tournament_keys = {
        row.tournament_key
        for row in [*fixtures, *next_rows]
        if getattr(row, "tournament_key", None) is not None
    }
    surfaces_by_tournament: dict[int, str | None] = {}
    if tournament_keys:
        for tournament in db.scalars(
            select(Tournament).where(Tournament.tournament_key.in_(tournament_keys))
        ).all():
            if tournament.tournament_key is not None:
                surfaces_by_tournament[int(tournament.tournament_key)] = (
                    tournament.tournament_sourface
                )

    fixture_by_key = {row.event_key: row for row in fixtures}
    next_by_key = {row.event_key: row for row in next_rows}
    contexts: dict[int, _MatchContext] = {}

    for event_key in event_keys:
        fixture = fixture_by_key.get(event_key)
        next_row = next_by_key.get(event_key)
        if fixture is not None:
            lifecycle = classify_match_lifecycle(
                event_status=fixture.event_status,
                event_winner=fixture.event_winner,
                event_final_result=fixture.event_final_result,
                event_live=fixture.event_live,
            )
            surface = None
            if fixture.tournament_key is not None:
                surface = surfaces_by_tournament.get(int(fixture.tournament_key))
            if surface is None and next_row is not None:
                surface = next_row.surface
            contexts[event_key] = _MatchContext(
                lifecycle=lifecycle,
                actual_winner=fixture.event_winner
                if fixture.event_winner in COMPLETED_WINNERS
                else None,
                player_1_name=fixture.event_first_player,
                player_2_name=fixture.event_second_player,
                surface=surface,
                event_date=fixture.event_date,
            )
            continue

        if next_row is not None:
            lifecycle = classify_match_lifecycle(
                event_status=next_row.event_status,
                event_winner=None,
                is_completed=next_row.is_completed,
            )
            surface = next_row.surface
            if surface is None and next_row.tournament_key is not None:
                surface = surfaces_by_tournament.get(int(next_row.tournament_key))
            contexts[event_key] = _MatchContext(
                lifecycle=lifecycle,
                actual_winner=None,
                player_1_name=next_row.event_first_player,
                player_2_name=next_row.event_second_player,
                surface=surface,
                event_date=next_row.event_date,
            )
            continue

        contexts[event_key] = _MatchContext(
            lifecycle="upcoming",
            actual_winner=None,
            player_1_name=None,
            player_2_name=None,
            surface=None,
            event_date=None,
        )
    return contexts


def _load_published_rows(
    db: Session,
    *,
    from_date: date | None,
    to_date: date | None,
    event_date_from: date | None,
    event_date_to: date | None,
    model_version: str | None,
    model_name: str | None,
    publication_source: str | None,
    tournament_name: str | None,
    latest_only: bool,
) -> list[PublishedPrediction]:
    from datetime import time as time_cls

    stmt = select(PublishedPrediction)
    if from_date is not None:
        stmt = stmt.where(
            PublishedPrediction.published_at >= datetime.combine(from_date, time_cls.min)
        )
    if to_date is not None:
        stmt = stmt.where(
            PublishedPrediction.published_at <= datetime.combine(to_date, time_cls.max)
        )
    if event_date_from is not None:
        stmt = stmt.where(PublishedPrediction.event_date >= event_date_from)
    if event_date_to is not None:
        stmt = stmt.where(PublishedPrediction.event_date <= event_date_to)
    if model_version:
        stmt = stmt.where(PublishedPrediction.model_version == model_version)
    if model_name:
        stmt = stmt.where(PublishedPrediction.model_name == model_name)
    if publication_source:
        stmt = stmt.where(PublishedPrediction.publication_source == publication_source)
    if tournament_name:
        needle = tournament_name.strip()
        if needle:
            stmt = stmt.where(PublishedPrediction.tournament_name.ilike(f"%{needle}%"))

    if latest_only:
        latest_subq = (
            select(
                PublishedPrediction.publication_id.label("pid"),
                func.max(PublishedPrediction.content_version).label("max_v"),
            )
            .group_by(PublishedPrediction.publication_id)
            .subquery()
        )
        join_on = (PublishedPrediction.publication_id == latest_subq.c.pid) & (
            PublishedPrediction.content_version == latest_subq.c.max_v
        )
        stmt = stmt.join(latest_subq, join_on)

    rows = list(db.scalars(stmt).all())
    rows.sort(
        key=lambda row: (
            row.event_date or date.max,
            row.published_at,
            row.id,
        )
    )
    return rows


def _load_odds_snapshots(
    db: Session, event_keys: list[int]
) -> dict[int, list[PrematchOddsSnapshot]]:
    if not event_keys:
        return {}
    rows = list(
        db.scalars(
            select(PrematchOddsSnapshot).where(
                PrematchOddsSnapshot.event_key.in_(event_keys),
                PrematchOddsSnapshot.snapshot_type.in_(
                    ("opening", "observed", "publication", "closing")
                ),
            )
        ).all()
    )
    grouped: dict[int, list[PrematchOddsSnapshot]] = defaultdict(list)
    for row in rows:
        grouped[int(row.event_key)].append(row)
    return grouped


def _normalize_odds_band(odds_band: str | None) -> OddsBand | None:
    if odds_band is None:
        return None
    key = odds_band.strip()
    if not key:
        return None
    if key not in VALID_ODDS_BANDS:
        raise ValueError(
            f"odds_band non valido: {odds_band!r}. "
            f"Valori ammessi: {', '.join(sorted(VALID_ODDS_BANDS))}."
        )
    return key  # type: ignore[return-value]


def _apply_context_filters(
    settled: list[_SettledTip],
    *,
    surface: str | None,
    odds_band: OddsBand | None,
) -> list[_SettledTip]:
    result = settled
    if surface:
        needle = surface.strip().lower()
        if needle:
            result = [
                tip
                for tip in result
                if (tip.surface or "").strip().lower() == needle
            ]
    if odds_band is not None:
        result = [tip for tip in result if odds_bucket(tip.tip.odds) == odds_band]
    return result


def settle_published_tips(
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
) -> list[_SettledTip]:
    """Load published tips, settle at read time, apply surface/odds-band filters."""
    band = _normalize_odds_band(odds_band)
    rows = _load_published_rows(
        db,
        from_date=from_date,
        to_date=to_date,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        model_version=model_version,
        model_name=model_name,
        publication_source=publication_source,
        tournament_name=tournament_name,
        latest_only=latest_only,
    )
    contexts = _load_match_contexts(db, [row.event_key for row in rows])
    snapshots = _load_odds_snapshots(db, [row.event_key for row in rows])
    settled = [
        _settle_tip(
            row,
            contexts.get(row.event_key)
            or _MatchContext(
                lifecycle="upcoming",
                actual_winner=None,
                player_1_name=row.player_1_name,
                player_2_name=row.player_2_name,
                surface=None,
                event_date=row.event_date,
            ),
            snapshots=snapshots.get(int(row.event_key), []),
        )
        for row in rows
    ]
    settled = _apply_context_filters(settled, surface=surface, odds_band=band)
    settled.sort(key=lambda item: (item.sort_date, item.sort_ts, item.tip.id))
    return settled


def latest_version_ids(db: Session, publication_ids: list[str]) -> set[int]:
    if not publication_ids:
        return set()
    rows = db.execute(
        select(
            PublishedPrediction.publication_id,
            func.max(PublishedPrediction.content_version).label("max_version"),
        )
        .where(PublishedPrediction.publication_id.in_(publication_ids))
        .group_by(PublishedPrediction.publication_id)
    ).all()
    latest_ids: set[int] = set()
    for publication_id, max_version in rows:
        row_id = db.scalar(
            select(PublishedPrediction.id).where(
                PublishedPrediction.publication_id == publication_id,
                PublishedPrediction.content_version == max_version,
            )
        )
        if row_id is not None:
            latest_ids.add(row_id)
    return latest_ids


def settled_tip_to_read(item: _SettledTip, *, is_latest: bool) -> PublishedSettledTipRead:
    tip = item.tip
    return PublishedSettledTipRead(
        id=tip.id,
        publication_id=tip.publication_id,
        content_version=tip.content_version,
        previous_version_id=tip.previous_version_id,
        event_key=tip.event_key,
        selection=tip.selection,
        model_version=tip.model_version,
        model_name=tip.model_name,
        probability=tip.probability,
        odds=tip.odds,
        void_odds=tip.void_odds,
        edge=tip.edge,
        publication_odds=item.clv.publication_odds,
        publication_bookmaker=item.clv.publication_bookmaker,
        closing_odds=item.clv.closing_odds,
        closing_bookmaker=item.clv.closing_bookmaker,
        no_vig_publication_prob=round_metric(item.clv.no_vig_publication_prob, 6),
        no_vig_closing_prob=round_metric(item.clv.no_vig_closing_prob, 6),
        clv_pct=round_metric(item.clv.clv_pct, 4),
        clv_prob_delta_pct=round_metric(item.clv.clv_prob_delta_pct, 4),
        clv_available=item.clv.clv_pct is not None,
        unit_stake=tip.unit_stake,
        published_at=tip.published_at,
        publication_source=tip.publication_source,
        initial_status=tip.initial_status,
        content_hash=tip.content_hash,
        player_1_name=tip.player_1_name,
        player_2_name=tip.player_2_name,
        tournament_name=tip.tournament_name,
        event_date=tip.event_date,
        event_time=tip.event_time,
        match_prediction_id=tip.match_prediction_id,
        betting_slip_pick_id=tip.betting_slip_pick_id,
        is_latest=is_latest,
        match_started=item.lifecycle != "upcoming",
        outcome=item.outcome,
        profit=round(item.profit, 6),
        stake_settled=round(item.stake_settled, 6),
        surface=item.surface,
    )


def list_settled_published_tips(
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
    outcome: Literal["pending", "won", "lost", "void"] | None = None,
    limit: int | None = None,
) -> list[PublishedSettledTipRead]:
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
    )
    if outcome is not None:
        settled = [tip for tip in settled if tip.outcome == outcome]
    latest_ids = latest_version_ids(db, [tip.tip.publication_id for tip in settled])
    items = [
        settled_tip_to_read(tip, is_latest=tip.tip.id in latest_ids) for tip in settled
    ]
    if limit is not None:
        return items[: max(limit, 0)]
    return items


def _no_vig_probability(
    *,
    event_snapshots: list[PrematchOddsSnapshot],
    snapshot_type: str,
    bookmaker: str,
    selection: str,
    counterpart_selection: str | None,
) -> float | None:
    if not counterpart_selection:
        return None
    same_market = [
        row
        for row in event_snapshots
        if row.snapshot_type == snapshot_type and row.bookmaker == bookmaker
    ]
    selected = next((row for row in same_market if row.selection == selection), None)
    opposite = next(
        (row for row in same_market if row.selection == counterpart_selection), None
    )
    if selected is None or opposite is None:
        return None
    inv_selected = 1.0 / float(selected.odds)
    inv_opposite = 1.0 / float(opposite.odds)
    denom = inv_selected + inv_opposite
    if denom <= 0:
        return None
    return inv_selected / denom


def _resolve_clv(
    tip: PublishedPrediction,
    context: _MatchContext,
    *,
    event_snapshots: list[PrematchOddsSnapshot],
) -> _TipClv:
    selection = tip.selection
    same_selection = [row for row in event_snapshots if row.selection == selection]
    publication_rows = [row for row in same_selection if row.snapshot_type == "publication"]
    closing_rows = [row for row in same_selection if row.snapshot_type == "closing"]

    publication_row: PrematchOddsSnapshot | None = None
    if publication_rows:
        publication_row = min(
            publication_rows,
            key=lambda row: abs((row.captured_at - tip.published_at).total_seconds()),
        )

    publication_odds = (
        float(publication_row.odds)
        if publication_row is not None
        else (float(tip.odds) if tip.odds is not None else None)
    )
    publication_bookmaker = publication_row.bookmaker if publication_row is not None else None

    closing_row: PrematchOddsSnapshot | None = None
    if publication_bookmaker:
        same_bookmaker = [row for row in closing_rows if row.bookmaker == publication_bookmaker]
        if same_bookmaker:
            closing_row = max(
                same_bookmaker, key=lambda row: (row.captured_at, row.id or 0)
            )
    if closing_row is None and closing_rows:
        latest_ts = max(row.captured_at for row in closing_rows)
        latest_rows = [row for row in closing_rows if row.captured_at == latest_ts]
        median_odds = median(float(row.odds) for row in latest_rows)
        closing_row = min(
            latest_rows,
            key=lambda row: (abs(float(row.odds) - median_odds), row.bookmaker),
        )

    closing_odds = float(closing_row.odds) if closing_row is not None else None
    closing_bookmaker = closing_row.bookmaker if closing_row is not None else None

    counterpart_selection = None
    if context.player_1_name and context.player_2_name:
        selected_key = selection.strip().lower()
        p1 = context.player_1_name.strip().lower()
        p2 = context.player_2_name.strip().lower()
        if selected_key == p1:
            counterpart_selection = context.player_2_name
        elif selected_key == p2:
            counterpart_selection = context.player_1_name

    no_vig_publication = None
    if publication_row is not None:
        no_vig_publication = _no_vig_probability(
            event_snapshots=event_snapshots,
            snapshot_type="publication",
            bookmaker=publication_row.bookmaker,
            selection=selection,
            counterpart_selection=counterpart_selection,
        )
    no_vig_closing = None
    if closing_row is not None:
        no_vig_closing = _no_vig_probability(
            event_snapshots=event_snapshots,
            snapshot_type="closing",
            bookmaker=closing_row.bookmaker,
            selection=selection,
            counterpart_selection=counterpart_selection,
        )

    clv_pct = None
    if publication_odds is not None and closing_odds is not None and closing_odds > 0:
        clv_pct = ((publication_odds / closing_odds) - 1.0) * 100.0

    clv_prob_delta_pct = None
    if no_vig_publication is not None and no_vig_closing is not None:
        clv_prob_delta_pct = (no_vig_closing - no_vig_publication) * 100.0

    return _TipClv(
        publication_odds=publication_odds,
        publication_bookmaker=publication_bookmaker,
        closing_odds=closing_odds,
        closing_bookmaker=closing_bookmaker,
        no_vig_publication_prob=no_vig_publication,
        no_vig_closing_prob=no_vig_closing,
        clv_pct=clv_pct,
        clv_prob_delta_pct=clv_prob_delta_pct,
    )


def _settle_tip(
    tip: PublishedPrediction,
    context: _MatchContext,
    *,
    snapshots: list[PrematchOddsSnapshot],
) -> _SettledTip:
    player_1 = tip.player_1_name or context.player_1_name
    player_2 = tip.player_2_name or context.player_2_name
    predicted = selection_to_predicted_winner(tip.selection, player_1, player_2)
    settlement = settle_simulated_bet(
        lifecycle=context.lifecycle,
        predicted_winner=predicted,
        actual_winner=context.actual_winner,
        market_odds=tip.odds,
        stake_units=float(tip.unit_stake),
    )
    sort_date = tip.event_date or context.event_date or tip.published_at.date()
    clv = _resolve_clv(tip, context, event_snapshots=snapshots)
    return _SettledTip(
        tip=tip,
        outcome=settlement.outcome,
        profit=float(settlement.profit_units),
        stake_settled=float(settlement.stake_units),
        surface=context.surface,
        lifecycle=context.lifecycle,
        clv=clv,
        sort_date=sort_date,
        sort_ts=tip.published_at,
    )


def _aggregate(tips: list[_SettledTip], *, key: str, label: str) -> PublishedLiveStatsBucket:
    won = sum(1 for tip in tips if tip.outcome == "won")
    lost = sum(1 for tip in tips if tip.outcome == "lost")
    void = sum(1 for tip in tips if tip.outcome == "void")
    open_count = sum(1 for tip in tips if tip.outcome == "pending")
    closed = won + lost
    stake_total = sum(float(tip.tip.unit_stake) for tip in tips)
    stake_settled = sum(tip.stake_settled for tip in tips)
    profit = sum(tip.profit for tip in tips)
    odds_values = [float(tip.tip.odds) for tip in tips if tip.tip.odds is not None]
    clv_values = [tip.clv.clv_pct for tip in tips if tip.clv.clv_pct is not None]
    clv_prob_deltas = [
        tip.clv.clv_prob_delta_pct
        for tip in tips
        if tip.clv.clv_prob_delta_pct is not None
    ]
    clv_count = len(clv_values)
    clv_missing = max(len(tips) - clv_count, 0)
    clv_positive = sum(1 for value in clv_values if value > 0)
    return PublishedLiveStatsBucket(
        key=key,
        label=label,
        predictions_total=len(tips),
        closed=closed,
        open=open_count,
        void=void,
        won=won,
        lost=lost,
        hit_rate_pct=round_metric(hit_rate_pct(won, lost), 4),
        stake_total=round(stake_total, 6),
        stake_settled=round(stake_settled, 6),
        profit=round(profit, 6),
        roi_pct=round_metric(roi_pct(profit, stake_settled), 4),
        yield_pct=round_metric(yield_pct(profit, stake_settled), 4),
        avg_odds=round_metric(average(odds_values), 4),
        clv_count=clv_count,
        clv_missing=clv_missing,
        clv_coverage_pct=round_metric(
            (clv_count / len(tips) * 100.0) if tips else None, 4
        ),
        clv_avg_pct=round_metric(average(clv_values), 4),
        clv_median_pct=round_metric(median(clv_values) if clv_values else None, 4),
        clv_positive_pct=round_metric(
            (clv_positive / clv_count * 100.0) if clv_count else None, 4
        ),
        clv_avg_prob_delta_pct=round_metric(average(clv_prob_deltas), 4),
    )


def _group_buckets(
    tips: list[_SettledTip],
    *,
    key_fn,
    label_fn,
    order: list[str] | None = None,
) -> list[PublishedLiveStatsBucket]:
    grouped: dict[str, list[_SettledTip]] = defaultdict(list)
    for tip in tips:
        grouped[key_fn(tip)].append(tip)
    keys = order if order is not None else sorted(grouped.keys())
    buckets: list[PublishedLiveStatsBucket] = []
    for key in keys:
        if key not in grouped:
            continue
        buckets.append(_aggregate(grouped[key], key=key, label=label_fn(key)))
    for key in sorted(grouped.keys()):
        if order is not None and key in order:
            continue
        if any(bucket.key == key for bucket in buckets):
            continue
        buckets.append(_aggregate(grouped[key], key=key, label=label_fn(key)))
    return buckets


def compute_published_live_stats(
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
) -> PublishedLiveStatsSummary:
    band = _normalize_odds_band(odds_band)
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
        odds_band=band,
        latest_only=latest_only,
    )

    summary_bucket = _aggregate(settled, key="all", label="Tutti")
    closed_chrono = [tip for tip in settled if tip.outcome in {"won", "lost"}]
    closed_outcomes: list[Literal["won", "lost"]] = [
        "won" if tip.outcome == "won" else "lost" for tip in closed_chrono
    ]
    max_win, max_loss = longest_streaks(closed_outcomes)
    drawdown = max_drawdown(tip.profit for tip in closed_chrono)

    return PublishedLiveStatsSummary(
        latest_only=latest_only,
        from_date=from_date,
        to_date=to_date,
        event_date_from=event_date_from,
        event_date_to=event_date_to,
        model_version=model_version,
        model_name=model_name,
        publication_source=publication_source,
        tournament_name=tournament_name,
        surface=surface,
        odds_band=band,
        predictions_total=summary_bucket.predictions_total,
        closed=summary_bucket.closed,
        open=summary_bucket.open,
        void=summary_bucket.void,
        won=summary_bucket.won,
        lost=summary_bucket.lost,
        hit_rate_pct=summary_bucket.hit_rate_pct,
        stake_total=summary_bucket.stake_total,
        stake_settled=summary_bucket.stake_settled,
        profit=summary_bucket.profit,
        roi_pct=summary_bucket.roi_pct,
        yield_pct=summary_bucket.yield_pct,
        avg_odds=summary_bucket.avg_odds,
        max_drawdown=round(drawdown, 6),
        max_winning_streak=max_win,
        max_losing_streak=max_loss,
        clv_count=summary_bucket.clv_count,
        clv_missing=summary_bucket.clv_missing,
        clv_coverage_pct=summary_bucket.clv_coverage_pct,
        clv_avg_pct=summary_bucket.clv_avg_pct,
        clv_median_pct=summary_bucket.clv_median_pct,
        clv_positive_pct=summary_bucket.clv_positive_pct,
        clv_avg_prob_delta_pct=summary_bucket.clv_avg_prob_delta_pct,
        by_model=_group_buckets(
            settled,
            key_fn=lambda tip: f"{tip.tip.model_version}|{tip.tip.model_name}",
            label_fn=lambda key: key.replace("|", " / "),
        ),
        by_odds=_group_buckets(
            settled,
            key_fn=lambda tip: odds_bucket(tip.tip.odds),
            label_fn=lambda key: ODDS_BUCKET_LABELS.get(key, key),
            order=list(ODDS_BUCKET_LABELS.keys()),
        ),
        by_edge=_group_buckets(
            settled,
            key_fn=lambda tip: edge_bucket(tip.tip.edge),
            label_fn=lambda key: EDGE_BUCKET_LABELS.get(key, key),
            order=list(EDGE_BUCKET_LABELS.keys()),
        ),
        by_surface=_group_buckets(
            settled,
            key_fn=lambda tip: (tip.surface or "unknown").strip() or "unknown",
            label_fn=lambda key: "Sconosciuta" if key == "unknown" else key,
        ),
        by_period=_group_buckets(
            settled,
            key_fn=lambda tip: period_key(tip.tip.event_date, tip.tip.published_at),
            label_fn=lambda key: key,
        ),
    )
