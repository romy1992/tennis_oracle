"""Admin live-beta dashboard aggregate (LIVE tipbook ops view).

Composes existing services without mixing training/backtest metrics into live KPIs.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.schemas.global_update import GlobalUpdateRunRead
from backend.src.app.schemas.imports import ImportStatusResponse
from backend.src.app.schemas.live_beta_dashboard import (
    LiveBetaBacktestNote,
    LiveBetaDashboardResponse,
    LiveBetaDataCompleteness,
    LiveBetaPipelineStatus,
    LiveBetaRecentError,
)
from backend.src.app.schemas.telegram_analytics import TelegramBotEventRead
from backend.src.app.services.global_update import (
    _run_to_read_dict,
    get_active_run,
    get_latest_run,
)
from backend.src.app.services.import_state import get_import_status
from backend.src.app.services.live_betting_metrics import round_metric
from backend.src.app.services.published_live_stats import (
    compute_published_live_stats,
    latest_version_ids,
    settle_published_tips,
    settled_tip_to_read,
)
from backend.src.app.services.telegram_analytics import compute_telegram_stats
from backend.src.entity.fixture import Fixture
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot
from backend.src.entity.telegram_bot_event import TelegramBotEvent


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round_metric((numerator / denominator) * 100.0, 4)


def _run_read(run) -> GlobalUpdateRunRead | None:
    if run is None:
        return None
    return GlobalUpdateRunRead.model_validate(_run_to_read_dict(run))


def _pipeline_status(db: Session) -> LiveBetaPipelineStatus:
    active = get_active_run(db)
    latest = get_latest_run(db)
    active_read = _run_read(active)
    latest_read = _run_read(latest)
    last_updated = None
    for candidate in (active_read, latest_read):
        if candidate is None:
            continue
        last_updated = candidate.finished_at or candidate.started_at
        if last_updated is not None:
            break
    import_status = ImportStatusResponse.model_validate(get_import_status(db))
    return LiveBetaPipelineStatus(
        active_run=active_read,
        latest_run=latest_read,
        last_updated_at=last_updated,
        import_status=import_status,
    )


def _data_completeness_from_settled(
    db: Session,
    settled,
) -> LiveBetaDataCompleteness:
    tips_total = len(settled)
    tips_with_odds = sum(1 for tip in settled if tip.tip.odds is not None)
    tips_with_event_date = sum(1 for tip in settled if tip.tip.event_date is not None)
    event_keys = {tip.tip.event_key for tip in settled}
    match_keys: set[int] = set()
    if event_keys:
        match_keys.update(
            int(key)
            for key in db.scalars(
                select(Fixture.event_key).where(Fixture.event_key.in_(event_keys))
            ).all()
        )
        match_keys.update(
            int(key)
            for key in db.scalars(
                select(NextFixture.event_key).where(NextFixture.event_key.in_(event_keys))
            ).all()
        )
    tips_with_match_context = sum(1 for tip in settled if tip.tip.event_key in match_keys)

    snapshot_keys: set[int] = set()
    type_counts = {"opening": 0, "observed": 0, "publication": 0, "closing": 0}
    if event_keys:
        snapshot_rows = db.execute(
            select(
                PrematchOddsSnapshot.event_key,
                PrematchOddsSnapshot.snapshot_type,
            ).where(PrematchOddsSnapshot.event_key.in_(event_keys))
        ).all()
        for event_key, snapshot_type in snapshot_rows:
            snapshot_keys.add(int(event_key))
            key = str(snapshot_type or "")
            if key in type_counts:
                type_counts[key] += 1

    return LiveBetaDataCompleteness(
        tips_total=tips_total,
        tips_with_odds=tips_with_odds,
        tips_with_odds_pct=_pct(tips_with_odds, tips_total),
        tips_with_event_date=tips_with_event_date,
        tips_with_event_date_pct=_pct(tips_with_event_date, tips_total),
        tips_with_match_context=tips_with_match_context,
        tips_with_match_context_pct=_pct(tips_with_match_context, tips_total),
        distinct_event_keys=len(event_keys),
        event_keys_with_odds_snapshot=len(snapshot_keys),
        odds_snapshot_coverage_pct=_pct(len(snapshot_keys), len(event_keys)),
        snapshots_opening=type_counts["opening"],
        snapshots_observed=type_counts["observed"],
        snapshots_publication=type_counts["publication"],
        snapshots_closing=type_counts["closing"],
    )


def _recent_errors(db: Session, *, limit: int = 15) -> list[LiveBetaRecentError]:
    errors: list[LiveBetaRecentError] = []

    latest = get_latest_run(db)
    if latest is not None:
        run_read = _run_read(latest)
        assert run_read is not None
        stamp = run_read.finished_at or run_read.started_at
        for message in run_read.errors:
            errors.append(
                LiveBetaRecentError(
                    source="global_update",
                    created_at=stamp,
                    message=message,
                    detail=f"run_id={run_read.id} status={run_read.status}",
                )
            )
        for item in run_read.items:
            if item.error_message:
                errors.append(
                    LiveBetaRecentError(
                        source="global_update",
                        created_at=item.finished_at or item.started_at or stamp,
                        message=item.error_message,
                        detail=(
                            f"run_id={run_read.id} "
                            f"{item.model_version}/{item.model_name}"
                        ),
                    )
                )

    failed_events = db.scalars(
        select(TelegramBotEvent)
        .where(TelegramBotEvent.success.is_(False))
        .order_by(TelegramBotEvent.created_at.desc(), TelegramBotEvent.id.desc())
        .limit(limit)
    ).all()
    for row in failed_events:
        event = TelegramBotEventRead.model_validate(row)
        errors.append(
            LiveBetaRecentError(
                source="telegram",
                created_at=event.created_at,
                message=event.error_message or f"Azione fallita: {event.action}",
                detail=f"action={event.action} event_type={event.event_type}",
            )
        )

    errors.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
    return errors[:limit]


def compute_live_beta_dashboard(
    db: Session,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    model_version: str | None = None,
    model_name: str | None = None,
    tournament_name: str | None = None,
    surface: str | None = None,
    odds_band: str | None = None,
    latest_only: bool = True,
    tip_limit: int = 25,
) -> LiveBetaDashboardResponse:
    today = date.today()
    range_from = from_date or (today - timedelta(days=89))
    range_to = to_date or today

    filter_kwargs = {
        "model_version": model_version,
        "model_name": model_name,
        "tournament_name": tournament_name,
        "surface": surface,
        "odds_band": odds_band,
        "latest_only": latest_only,
    }

    live_stats = compute_published_live_stats(
        db,
        from_date=range_from,
        to_date=range_to,
        **filter_kwargs,
    )
    settled = settle_published_tips(
        db,
        from_date=range_from,
        to_date=range_to,
        **filter_kwargs,
    )
    today_settled = settle_published_tips(
        db,
        from_date=today,
        to_date=today,
        **filter_kwargs,
    )
    latest_ids = latest_version_ids(
        db,
        [tip.tip.publication_id for tip in [*settled, *today_settled]],
    )

    def _reads(items, *, limit: int | None = tip_limit):
        rows = [
            settled_tip_to_read(tip, is_latest=tip.tip.id in latest_ids) for tip in items
        ]
        if limit is None:
            return rows
        return rows[: max(limit, 0)]

    open_items = [tip for tip in settled if tip.outcome == "pending"]
    closed_items = [
        tip for tip in settled if tip.outcome in {"won", "lost", "void"}
    ]
    closed_items.sort(key=lambda tip: (tip.sort_date, tip.sort_ts, tip.tip.id), reverse=True)

    bot_usage = compute_telegram_stats(db, from_date=range_from, to_date=range_to)

    return LiveBetaDashboardResponse(
        generated_at=datetime.now(),
        from_date=range_from,
        to_date=range_to,
        model_version=model_version,
        model_name=model_name,
        tournament_name=tournament_name,
        surface=surface,
        odds_band=live_stats.odds_band,
        latest_only=latest_only,
        pipeline=_pipeline_status(db),
        live_stats=live_stats,
        published_today=_reads(today_settled),
        open_predictions=_reads(open_items),
        closed_predictions=_reads(closed_items),
        bot_usage=bot_usage,
        data_completeness=_data_completeness_from_settled(db, settled),
        recent_errors=_recent_errors(db),
        backtest=LiveBetaBacktestNote(),
    )
