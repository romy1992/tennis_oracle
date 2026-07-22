"""Admin live-beta dashboard aggregate (LIVE tipbook ops view).

Composes existing services without mixing training/backtest metrics into live KPIs.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from backend.src.app.schemas.global_update import GlobalUpdateRunRead
from backend.src.app.schemas.imports import ImportStatusResponse
from backend.src.app.schemas.live_beta_dashboard import (
    LiveBetaBacktestNote,
    LiveBetaDashboardResponse,
    LiveBetaDataCompleteness,
    LiveBetaPipelineStatus,
    LiveBetaPublicationHealth,
    LiveBetaRecentError,
    LivePublicationEmptyReason,
)
from backend.src.app.schemas.telegram_analytics import TelegramBotEventRead
from backend.src.app.services.global_update import (
    _run_to_read_dict,
    get_active_run,
    get_latest_run,
)
from backend.src.app.services.import_state import get_import_status
from backend.src.app.services.live_betting_metrics import round_metric
from backend.src.app.services.live_publication_service import resolve_public_model_config
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
from backend.src.entity.published_prediction import PublishedPrediction
from backend.src.entity.telegram_bot_event import TelegramBotEvent

logger = logging.getLogger(__name__)

CLOSING_NOTE = (
    "Closing odds: senza un job dedicato di cattura pre-kickoff frequente, "
    "il closing è best-effort (ultimo observed pre-match etichettato a partita live). "
    "Un job futuro dovrà acquisire la quota immediatamente prima dell'inizio."
)


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


def _table_available(db: Session, table_name: str) -> bool:
    try:
        return table_name in set(inspect(db.get_bind()).get_table_names())
    except Exception:  # noqa: BLE001
        logger.exception("Failed to inspect tables for live beta dashboard")
        return False


def _parse_live_publication_from_run(run) -> dict[str, Any]:
    if run is None:
        return {}
    if run.report_json:
        try:
            report = json.loads(run.report_json)
            summary = report.get("summary") or {}
            live = summary.get("live_publication")
            if isinstance(live, dict):
                return live
        except (TypeError, json.JSONDecodeError):
            pass
    warnings = []
    if run.warnings_json:
        try:
            warnings = json.loads(run.warnings_json)
        except (TypeError, json.JSONDecodeError):
            warnings = []
    for warning in warnings:
        if isinstance(warning, str) and warning.startswith("live_publication_summary:"):
            raw = warning.split(":", 1)[1]
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return {}


def _validation_started_at(db: Session) -> datetime | None:
    return db.scalar(select(func.min(PublishedPrediction.published_at)))


def _publication_health(
    db: Session,
    *,
    tips_total: int,
    pipeline: LiveBetaPipelineStatus,
) -> LiveBetaPublicationHealth:
    public = resolve_public_model_config()
    latest = pipeline.latest_run
    live_from_run = _parse_live_publication_from_run(
        get_latest_run(db) if latest is not None else None
    )
    created = live_from_run.get("publications_created")
    duplicates = live_from_run.get("duplicates_skipped")
    excluded = live_from_run.get("predictions_excluded")
    candidates = live_from_run.get("candidates_evaluated")
    pub_errors = live_from_run.get("publication_errors") or []
    if not isinstance(pub_errors, list):
        pub_errors = [str(pub_errors)]

    validation_started = None
    if _table_available(db, "published_prediction"):
        validation_started = _validation_started_at(db)
    else:
        return LiveBetaPublicationHealth(
            empty_reason="table_unavailable",
            message=(
                "La tabella published_prediction non è disponibile. "
                "Esegui le migrazioni Alembic (fino a 0015) prima di usare il registro live."
            ),
            live_publication_enabled=public.enabled,
            public_model_version=public.model_version,
            public_model_name=public.model_name,
            last_run_publication_errors=[],
        )

    reason: LivePublicationEmptyReason = "ok"
    message = "Registro live operativo."

    if tips_total == 0:
        if public.status == "disabled":
            reason = "publication_disabled"
            message = (
                "Nessuna pubblicazione: LIVE_PUBLICATION_ENABLED=false. "
                "La pipeline genera previsioni/schedine ma non scrive il registro live."
            )
        elif public.status == "incomplete":
            reason = "public_model_unconfigured"
            message = (
                "Pubblicazione live abilitata ma PUBLIC_MODEL_VERSION / "
                "PUBLIC_MODEL_NAME non sono configurati. Nessun fallback automatico."
            )
        elif public.status == "invalid":
            reason = "public_model_invalid"
            message = public.warning or "Configurazione modello pubblico non valida."
        elif latest is None:
            reason = "pipeline_never_run"
            message = (
                "Nessun aggiornamento globale eseguito ancora. "
                "Avvia l'aggiornamento globale dopo aver abilitato la pubblicazione live."
            )
        elif pub_errors or live_from_run.get("config_status") == "error":
            reason = "publication_errors"
            message = (
                "L'ultimo aggiornamento ha riportato errori di pubblicazione live. "
                "Controlla il report global-update e gli errori qui sotto."
            )
        else:
            reason = "pipeline_run_no_qualified_plays"
            message = (
                "Pipeline eseguita, ma nessuna giocata PLAY qualificata è stata "
                "pubblicata per il modello pubblico (edge insufficiente, quote "
                "mancanti, partite già iniziate o duplicati)."
            )

    return LiveBetaPublicationHealth(
        empty_reason=reason,
        message=message,
        live_publication_enabled=public.enabled,
        public_model_version=public.model_version,
        public_model_name=public.model_name,
        validation_started_at=validation_started,
        last_run_publications_created=int(created) if created is not None else None,
        last_run_duplicates_skipped=int(duplicates) if duplicates is not None else None,
        last_run_excluded=int(excluded) if excluded is not None else None,
        last_run_candidates=int(candidates) if candidates is not None else None,
        last_run_publication_errors=[str(item) for item in pub_errors],
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
    closing_keys: set[int] = set()
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
            if key == "closing":
                closing_keys.add(int(event_key))

    tips_with_closing = sum(1 for tip in settled if tip.tip.event_key in closing_keys)
    closing_pct = _pct(tips_with_closing, tips_total)
    if tips_total == 0:
        closing_status = "unknown"
    elif tips_with_closing == 0:
        closing_status = "missing"
    elif tips_with_closing < tips_total:
        closing_status = "partial"
    else:
        closing_status = "available"

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
        tips_with_closing_snapshot=tips_with_closing,
        tips_with_closing_snapshot_pct=closing_pct,
        closing_odds_status=closing_status,
        closing_odds_note=CLOSING_NOTE,
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
    pipeline = _pipeline_status(db)

    filter_kwargs = {
        "model_version": model_version,
        "model_name": model_name,
        "tournament_name": tournament_name,
        "surface": surface,
        "odds_band": odds_band,
        "latest_only": latest_only,
    }

    if not _table_available(db, "published_prediction"):
        from backend.src.app.schemas.published_prediction import PublishedLiveStatsSummary
        from backend.src.app.schemas.telegram_analytics import TelegramBotStatsResponse

        empty_stats = PublishedLiveStatsSummary(
            from_date=range_from,
            to_date=range_to,
            model_version=model_version,
            model_name=model_name,
            tournament_name=tournament_name,
            surface=surface,
            odds_band=odds_band,  # type: ignore[arg-type]
            publication_source=None,
            latest_only=latest_only,
            predictions_total=0,
            closed=0,
            open=0,
            void=0,
            won=0,
            lost=0,
            hit_rate_pct=None,
            stake_total=0.0,
            stake_settled=0.0,
            profit=0.0,
            roi_pct=None,
            yield_pct=None,
            avg_odds=None,
            max_drawdown=0.0,
            max_winning_streak=0,
            max_losing_streak=0,
            by_model=[],
            by_odds=[],
            by_edge=[],
            by_surface=[],
            by_period=[],
        )
        health = _publication_health(db, tips_total=0, pipeline=pipeline)
        return LiveBetaDashboardResponse(
            generated_at=datetime.now(),
            from_date=range_from,
            to_date=range_to,
            model_version=model_version,
            model_name=model_name,
            tournament_name=tournament_name,
            surface=surface,
            odds_band=None,
            latest_only=latest_only,
            pipeline=pipeline,
            publication_health=health,
            live_stats=empty_stats,
            published_today=[],
            open_predictions=[],
            closed_predictions=[],
            bot_usage=TelegramBotStatsResponse(
                total_events=0,
                events_today=0,
                unique_users=0,
                top_action=None,
                by_action=[],
                by_day=[],
            ),
            data_completeness=LiveBetaDataCompleteness(closing_odds_note=CLOSING_NOTE),
            recent_errors=_recent_errors(db),
            backtest=LiveBetaBacktestNote(),
        )

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
    completeness = _data_completeness_from_settled(db, settled)
    health = _publication_health(
        db,
        tips_total=live_stats.predictions_total,
        pipeline=pipeline,
    )

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
        pipeline=pipeline,
        publication_health=health,
        live_stats=live_stats,
        published_today=_reads(today_settled),
        open_predictions=_reads(open_items),
        closed_predictions=_reads(closed_items),
        bot_usage=bot_usage,
        data_completeness=completeness,
        recent_errors=_recent_errors(db),
        backtest=LiveBetaBacktestNote(),
    )
