"""Weekly beta report: aggregate KPIs, persist, notify admin via Telegram."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.observability.alerts import send_admin_alert
from backend.src.app.schemas.weekly_beta_report import (
    WeeklyBetaCommandUsage,
    WeeklyBetaFeedbackMetrics,
    WeeklyBetaLiveTipsMetrics,
    WeeklyBetaMetricDelta,
    WeeklyBetaNotificationsMetrics,
    WeeklyBetaPeriodMetrics,
    WeeklyBetaPipelineMetrics,
    WeeklyBetaReportListItem,
    WeeklyBetaReportPayload,
    WeeklyBetaReportRead,
    WeeklyBetaUsersMetrics,
    WeeklyBetaWowDeltas,
)
from backend.src.app.services.live_betting_metrics import round_metric
from backend.src.app.services.published_live_stats import compute_published_live_stats
from backend.src.app.services.telegram_analytics import compute_telegram_stats
from backend.src.entity.global_update_run import GlobalUpdateRun
from backend.src.entity.telegram_feedback import TelegramFeedback
from backend.src.entity.telegram_notification_delivery import TelegramNotificationDelivery
from backend.src.entity.telegram_user import TelegramUser
from backend.src.entity.weekly_beta_report import WeeklyBetaReport

logger = logging.getLogger(__name__)

ROME_TZ = ZoneInfo("Europe/Rome")
PIPELINE_ERROR_STATUSES = frozenset({"failed", "completed_with_errors", "interrupted"})
MAX_PIPELINE_ERROR_MESSAGES = 20


def _week_label(week_start: date) -> str:
    iso = week_start.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def iso_week_bounds(day: date) -> tuple[date, date]:
    """Return Monday–Sunday inclusive for the ISO week containing ``day``."""
    week_start = day - timedelta(days=day.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def previous_completed_iso_week(*, today: date | None = None) -> tuple[date, date]:
    """Default report window: last fully completed ISO week (Mon–Sun) in Rome."""
    ref = today or datetime.now(ROME_TZ).date()
    this_start, _ = iso_week_bounds(ref)
    prev_end = this_start - timedelta(days=1)
    return iso_week_bounds(prev_end)


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min)


def _day_end_exclusive(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time.min)


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round_metric((numerator / denominator) * 100.0, 4)


def _metric_delta(current: float | int | None, previous: float | int | None) -> WeeklyBetaMetricDelta:
    if current is None and previous is None:
        return WeeklyBetaMetricDelta()
    delta: float | int | None = None
    delta_pct: float | None = None
    if current is not None and previous is not None:
        if isinstance(current, int) and isinstance(previous, int):
            delta = current - previous
        else:
            delta = round_metric(float(current) - float(previous), 4)
        if previous not in (0, 0.0):
            delta_pct = round_metric((float(delta) / float(previous)) * 100.0, 4)
    return WeeklyBetaMetricDelta(
        current=current,
        previous=previous,
        delta=delta,
        delta_pct=delta_pct,
    )


def _count_users_by_status(db: Session, *, as_of_end: date) -> dict[str, int]:
    end = _day_end_exclusive(as_of_end)
    rows = db.execute(
        select(TelegramUser.status, func.count())
        .where(TelegramUser.created_at < end)
        .group_by(TelegramUser.status)
    ).all()
    return {str(status): int(count) for status, count in rows}


def _users_metrics(db: Session, *, week_start: date, week_end: date) -> WeeklyBetaUsersMetrics:
    start_dt = _day_start(week_start)
    end_dt = _day_end_exclusive(week_end)
    prev_start = week_start - timedelta(days=7)
    prev_end = week_start - timedelta(days=1)
    prev_start_dt = _day_start(prev_start)
    prev_end_dt = _day_end_exclusive(prev_end)

    total_users = int(
        db.scalar(
            select(func.count()).select_from(TelegramUser).where(TelegramUser.created_at < end_dt)
        )
        or 0
    )
    active_users = int(
        db.scalar(
            select(func.count())
            .select_from(TelegramUser)
            .where(
                TelegramUser.last_access_at >= start_dt,
                TelegramUser.last_access_at < end_dt,
            )
        )
        or 0
    )
    new_users = int(
        db.scalar(
            select(func.count())
            .select_from(TelegramUser)
            .where(
                TelegramUser.created_at >= start_dt,
                TelegramUser.created_at < end_dt,
            )
        )
        or 0
    )
    by_status = _count_users_by_status(db, as_of_end=week_end)

    # Retention: cohort = first_access in previous week; retained = last_access this week.
    cohort_ids = list(
        db.scalars(
            select(TelegramUser.telegram_user_id).where(
                TelegramUser.first_access_at >= prev_start_dt,
                TelegramUser.first_access_at < prev_end_dt,
            )
        ).all()
    )
    retention_cohort = len(cohort_ids)
    retention_retained = 0
    if cohort_ids:
        retention_retained = int(
            db.scalar(
                select(func.count())
                .select_from(TelegramUser)
                .where(
                    TelegramUser.telegram_user_id.in_(cohort_ids),
                    TelegramUser.last_access_at >= start_dt,
                    TelegramUser.last_access_at < end_dt,
                )
            )
            or 0
        )

    return WeeklyBetaUsersMetrics(
        total_users=total_users,
        active_users=active_users,
        new_users=new_users,
        by_status=by_status,
        retention_cohort=retention_cohort,
        retention_retained=retention_retained,
        retention_pct=_pct(retention_retained, retention_cohort),
    )


def _command_usage(db: Session, *, week_start: date, week_end: date) -> WeeklyBetaCommandUsage:
    stats = compute_telegram_stats(db, from_date=week_start, to_date=week_end)
    return WeeklyBetaCommandUsage(
        total_events=stats.total_events,
        unique_users=stats.unique_users,
        by_action=list(stats.by_action),
    )


def _live_tips(db: Session, *, week_start: date, week_end: date) -> WeeklyBetaLiveTipsMetrics:
    summary = compute_published_live_stats(
        db,
        from_date=week_start,
        to_date=week_end,
        latest_only=True,
    )
    return WeeklyBetaLiveTipsMetrics(
        predictions_published=summary.predictions_total,
        closed=summary.closed,
        open=summary.open,
        won=summary.won,
        lost=summary.lost,
        void=summary.void,
        hit_rate_pct=summary.hit_rate_pct,
        stake_settled=summary.stake_settled,
        profit=summary.profit,
        roi_pct=summary.roi_pct,
        yield_pct=summary.yield_pct,
        max_drawdown=summary.max_drawdown,
    )


def _pipeline_metrics(db: Session, *, week_start: date, week_end: date) -> WeeklyBetaPipelineMetrics:
    runs = list(
        db.scalars(
            select(GlobalUpdateRun).where(
                GlobalUpdateRun.run_date >= week_start,
                GlobalUpdateRun.run_date <= week_end,
            )
        ).all()
    )
    failed = sum(1 for r in runs if r.status == "failed")
    with_errors = sum(1 for r in runs if r.status == "completed_with_errors")
    interrupted = sum(1 for r in runs if r.status == "interrupted")
    combinations_failed = sum(int(r.combinations_failed or 0) for r in runs)

    messages: list[str] = []
    for run in runs:
        if run.status not in PIPELINE_ERROR_STATUSES:
            continue
        if run.errors_json:
            try:
                parsed = json.loads(run.errors_json)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, str) and item.strip():
                            messages.append(f"run#{run.id}: {item.strip()[:200]}")
                        elif isinstance(item, dict):
                            text = str(item.get("message") or item.get("error") or item)[:200]
                            messages.append(f"run#{run.id}: {text}")
                elif isinstance(parsed, dict):
                    messages.append(f"run#{run.id}: {str(parsed)[:200]}")
            except (TypeError, json.JSONDecodeError):
                messages.append(f"run#{run.id}: {str(run.errors_json)[:200]}")
        else:
            messages.append(f"run#{run.id}: status={run.status}")
        if len(messages) >= MAX_PIPELINE_ERROR_MESSAGES:
            break

    return WeeklyBetaPipelineMetrics(
        runs_total=len(runs),
        runs_failed=failed,
        runs_completed_with_errors=with_errors,
        runs_interrupted=interrupted,
        combinations_failed=combinations_failed,
        error_messages=messages[:MAX_PIPELINE_ERROR_MESSAGES],
    )


def _notifications_metrics(
    db: Session, *, week_start: date, week_end: date
) -> WeeklyBetaNotificationsMetrics:
    start_dt = _day_start(week_start)
    end_dt = _day_end_exclusive(week_end)
    rows = db.execute(
        select(TelegramNotificationDelivery.status, func.count()).where(
            TelegramNotificationDelivery.created_at >= start_dt,
            TelegramNotificationDelivery.created_at < end_dt,
        ).group_by(TelegramNotificationDelivery.status)
    ).all()
    by_status = {str(status): int(count) for status, count in rows}
    failed_by_kind_rows = db.execute(
        select(TelegramNotificationDelivery.kind, func.count()).where(
            TelegramNotificationDelivery.created_at >= start_dt,
            TelegramNotificationDelivery.created_at < end_dt,
            TelegramNotificationDelivery.status == "failed",
        ).group_by(TelegramNotificationDelivery.kind)
    ).all()
    by_kind_failed = {str(kind): int(count) for kind, count in failed_by_kind_rows}
    total = sum(by_status.values())
    return WeeklyBetaNotificationsMetrics(
        total=total,
        sent=by_status.get("sent", 0),
        failed=by_status.get("failed", 0),
        skipped=by_status.get("skipped", 0),
        pending=by_status.get("pending", 0),
        by_kind_failed=by_kind_failed,
    )


def _feedback_metrics(db: Session, *, week_start: date, week_end: date) -> WeeklyBetaFeedbackMetrics:
    start_dt = _day_start(week_start)
    end_dt = _day_end_exclusive(week_end)
    total = int(
        db.scalar(
            select(func.count())
            .select_from(TelegramFeedback)
            .where(
                TelegramFeedback.created_at >= start_dt,
                TelegramFeedback.created_at < end_dt,
            )
        )
        or 0
    )
    avg_rating = db.scalar(
        select(func.avg(TelegramFeedback.rating)).where(
            TelegramFeedback.created_at >= start_dt,
            TelegramFeedback.created_at < end_dt,
        )
    )
    by_status_rows = db.execute(
        select(TelegramFeedback.status, func.count()).where(
            TelegramFeedback.created_at >= start_dt,
            TelegramFeedback.created_at < end_dt,
        ).group_by(TelegramFeedback.status)
    ).all()
    by_category_rows = db.execute(
        select(TelegramFeedback.category, func.count()).where(
            TelegramFeedback.created_at >= start_dt,
            TelegramFeedback.created_at < end_dt,
        ).group_by(TelegramFeedback.category)
    ).all()
    return WeeklyBetaFeedbackMetrics(
        total=total,
        avg_rating=round_metric(float(avg_rating), 2) if avg_rating is not None else None,
        by_status={str(s): int(c) for s, c in by_status_rows},
        by_category={str(c): int(n) for c, n in by_category_rows},
    )


def compute_period_metrics(
    db: Session, *, week_start: date, week_end: date
) -> WeeklyBetaPeriodMetrics:
    if week_end < week_start:
        raise ValueError("week_end must be >= week_start")
    if (week_end - week_start).days != 6:
        raise ValueError("week window must be exactly 7 days (Monday–Sunday)")
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday (ISO week)")

    return WeeklyBetaPeriodMetrics(
        week_start=week_start,
        week_end=week_end,
        week_label=_week_label(week_start),
        users=_users_metrics(db, week_start=week_start, week_end=week_end),
        command_usage=_command_usage(db, week_start=week_start, week_end=week_end),
        live_tips=_live_tips(db, week_start=week_start, week_end=week_end),
        pipeline=_pipeline_metrics(db, week_start=week_start, week_end=week_end),
        notifications=_notifications_metrics(db, week_start=week_start, week_end=week_end),
        feedback=_feedback_metrics(db, week_start=week_start, week_end=week_end),
    )


def build_wow_deltas(
    current: WeeklyBetaPeriodMetrics, previous: WeeklyBetaPeriodMetrics
) -> WeeklyBetaWowDeltas:
    cur_pipe_errors = (
        current.pipeline.runs_failed
        + current.pipeline.runs_completed_with_errors
        + current.pipeline.runs_interrupted
    )
    prev_pipe_errors = (
        previous.pipeline.runs_failed
        + previous.pipeline.runs_completed_with_errors
        + previous.pipeline.runs_interrupted
    )
    return WeeklyBetaWowDeltas(
        total_users=_metric_delta(current.users.total_users, previous.users.total_users),
        active_users=_metric_delta(current.users.active_users, previous.users.active_users),
        new_users=_metric_delta(current.users.new_users, previous.users.new_users),
        retention_pct=_metric_delta(current.users.retention_pct, previous.users.retention_pct),
        total_events=_metric_delta(
            current.command_usage.total_events, previous.command_usage.total_events
        ),
        predictions_published=_metric_delta(
            current.live_tips.predictions_published,
            previous.live_tips.predictions_published,
        ),
        roi_pct=_metric_delta(current.live_tips.roi_pct, previous.live_tips.roi_pct),
        yield_pct=_metric_delta(current.live_tips.yield_pct, previous.live_tips.yield_pct),
        max_drawdown=_metric_delta(
            current.live_tips.max_drawdown, previous.live_tips.max_drawdown
        ),
        pipeline_errors=_metric_delta(cur_pipe_errors, prev_pipe_errors),
        notifications_failed=_metric_delta(
            current.notifications.failed, previous.notifications.failed
        ),
        feedback_total=_metric_delta(current.feedback.total, previous.feedback.total),
    )


def compute_weekly_beta_report_payload(
    db: Session, *, week_start: date, week_end: date | None = None
) -> WeeklyBetaReportPayload:
    if week_end is None:
        week_end = week_start + timedelta(days=6)
    current = compute_period_metrics(db, week_start=week_start, week_end=week_end)
    prev_start = week_start - timedelta(days=7)
    prev_end = week_start - timedelta(days=1)
    previous = compute_period_metrics(db, week_start=prev_start, week_end=prev_end)
    wow = build_wow_deltas(current, previous)
    notes = [
        "Settimana ISO (lunedì–domenica) in calendario Europe/Rome.",
        "Utenti attivi: last_access_at nella settimana.",
        "Retention: utenti con first_access nella settimana precedente e last_access in quella corrente.",
        "ROI / yield / drawdown: tipbook live (published_prediction), latest version only.",
    ]
    return WeeklyBetaReportPayload(
        current=current,
        previous=previous,
        wow=wow,
        notes=notes,
    )


def _payload_from_row(row: WeeklyBetaReport) -> WeeklyBetaReportPayload:
    raw = json.loads(row.payload_json)
    return WeeklyBetaReportPayload.model_validate(raw)


def report_to_read(row: WeeklyBetaReport) -> WeeklyBetaReportRead:
    return WeeklyBetaReportRead(
        id=row.id,
        week_start=row.week_start,
        week_end=row.week_end,
        week_label=row.week_label,
        payload=_payload_from_row(row),
        telegram_status=row.telegram_status,  # type: ignore[arg-type]
        telegram_error=row.telegram_error,
        telegram_sent_at=row.telegram_sent_at,
        generated_at=row.generated_at,
        generated_by=row.generated_by,
    )


def report_to_list_item(row: WeeklyBetaReport) -> WeeklyBetaReportListItem:
    payload = _payload_from_row(row)
    cur = payload.current
    return WeeklyBetaReportListItem(
        id=row.id,
        week_start=row.week_start,
        week_end=row.week_end,
        week_label=row.week_label,
        telegram_status=row.telegram_status,  # type: ignore[arg-type]
        telegram_sent_at=row.telegram_sent_at,
        generated_at=row.generated_at,
        generated_by=row.generated_by,
        total_users=cur.users.total_users,
        active_users=cur.users.active_users,
        new_users=cur.users.new_users,
        retention_pct=cur.users.retention_pct,
        predictions_published=cur.live_tips.predictions_published,
        roi_pct=cur.live_tips.roi_pct,
        notifications_failed=cur.notifications.failed,
        feedback_total=cur.feedback.total,
    )


def get_weekly_beta_report(db: Session, report_id: int) -> WeeklyBetaReport | None:
    return db.get(WeeklyBetaReport, report_id)


def get_latest_weekly_beta_report(db: Session) -> WeeklyBetaReport | None:
    return db.scalar(
        select(WeeklyBetaReport).order_by(WeeklyBetaReport.week_start.desc(), WeeklyBetaReport.id.desc())
    )


def list_weekly_beta_reports(
    db: Session, *, limit: int = 20, offset: int = 0
) -> tuple[list[WeeklyBetaReport], int]:
    total = int(db.scalar(select(func.count()).select_from(WeeklyBetaReport)) or 0)
    rows = list(
        db.scalars(
            select(WeeklyBetaReport)
            .order_by(WeeklyBetaReport.week_start.desc(), WeeklyBetaReport.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return rows, total


def format_admin_telegram_summary(payload: WeeklyBetaReportPayload) -> str:
    cur = payload.current
    wow = payload.wow

    def _fmt_delta(d: WeeklyBetaMetricDelta, *, pct: bool = False, digits: int = 1) -> str:
        if d.delta is None:
            return "n/d"
        sign = "+" if float(d.delta) > 0 else ""
        if pct:
            return f"{sign}{float(d.delta):.{digits}f} pp"
        if isinstance(d.current, int) and isinstance(d.previous, int):
            return f"{sign}{int(d.delta)}"
        return f"{sign}{float(d.delta):.{digits}f}"

    top_actions = ", ".join(
        f"{a.action}={a.count}" for a in cur.command_usage.by_action[:5]
    ) or "nessuno"
    ret = (
        f"{cur.users.retention_pct:.1f}%"
        if cur.users.retention_pct is not None
        else "n/d"
    )
    roi = f"{cur.live_tips.roi_pct:.2f}%" if cur.live_tips.roi_pct is not None else "n/d"
    yld = f"{cur.live_tips.yield_pct:.2f}%" if cur.live_tips.yield_pct is not None else "n/d"
    pipe_err = (
        cur.pipeline.runs_failed
        + cur.pipeline.runs_completed_with_errors
        + cur.pipeline.runs_interrupted
    )

    lines = [
        f"Report beta settimanale {cur.week_label}",
        f"Periodo: {cur.week_start.isoformat()} → {cur.week_end.isoformat()}",
        "",
        f"Utenti: totali={cur.users.total_users} ({_fmt_delta(wow.total_users)}), "
        f"attivi={cur.users.active_users} ({_fmt_delta(wow.active_users)}), "
        f"nuovi={cur.users.new_users} ({_fmt_delta(wow.new_users)})",
        f"Retention W1: {ret} (coorte={cur.users.retention_cohort}, "
        f"retained={cur.users.retention_retained}) [{_fmt_delta(wow.retention_pct, pct=True)}]",
        f"Comandi: eventi={cur.command_usage.total_events} "
        f"({_fmt_delta(wow.total_events)}), utenti unici={cur.command_usage.unique_users}",
        f"Top azioni: {top_actions}",
        f"Pronostici pubblicati: {cur.live_tips.predictions_published} "
        f"({_fmt_delta(wow.predictions_published)})",
        f"Live tipbook: ROI={roi} ({_fmt_delta(wow.roi_pct, pct=True, digits=2)}), "
        f"yield={yld} ({_fmt_delta(wow.yield_pct, pct=True, digits=2)}), "
        f"drawdown={cur.live_tips.max_drawdown:.2f} "
        f"({_fmt_delta(wow.max_drawdown, digits=2)})",
        f"Pipeline errori: {pipe_err} ({_fmt_delta(wow.pipeline_errors)}) "
        f"[failed={cur.pipeline.runs_failed}, with_errors={cur.pipeline.runs_completed_with_errors}, "
        f"interrupted={cur.pipeline.runs_interrupted}]",
        f"Notifiche fallite: {cur.notifications.failed} ({_fmt_delta(wow.notifications_failed)}) "
        f"(inviate={cur.notifications.sent})",
        f"Feedback: {cur.feedback.total} ({_fmt_delta(wow.feedback_total)})"
        + (
            f", rating medio={cur.feedback.avg_rating}"
            if cur.feedback.avg_rating is not None
            else ""
        ),
    ]
    return "\n".join(lines)


def send_weekly_report_telegram(
    payload: WeeklyBetaReportPayload,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    enabled = bool(getattr(cfg, "weekly_beta_report_telegram_enabled", True))
    message = format_admin_telegram_summary(payload)
    return send_admin_alert(
        message,
        severity="info",
        dedupe_key=f"weekly-beta-report:{payload.current.week_label}",
        telegram_bot_token=cfg.telegram_bot_token,
        telegram_admin_chat_id=cfg.telegram_admin_chat_id,
        webhook_url=None,
        cooldown_seconds=0,
        enabled=enabled,
    )


def generate_and_store_weekly_beta_report(
    db: Session,
    *,
    week_start: date | None = None,
    settings: Settings | None = None,
    send_telegram: bool = True,
    force: bool = False,
    generated_by: str = "job",
) -> tuple[WeeklyBetaReport, bool, dict[str, Any]]:
    """Compute, upsert, optionally Telegram-notify. Returns (row, created, telegram_result)."""
    cfg = settings or get_settings()
    if week_start is None:
        week_start, week_end = previous_completed_iso_week()
    else:
        week_end = week_start + timedelta(days=6)

    existing = db.scalar(
        select(WeeklyBetaReport).where(
            WeeklyBetaReport.week_start == week_start,
            WeeklyBetaReport.week_end == week_end,
        )
    )
    if existing is not None and not force:
        telegram_result: dict[str, Any] = {"skipped": True, "reason": "already_exists"}
        if send_telegram and existing.telegram_status != "sent":
            payload = _payload_from_row(existing)
            telegram_result = send_weekly_report_telegram(payload, settings=cfg)
            _apply_telegram_result(existing, telegram_result)
            db.commit()
            db.refresh(existing)
        return existing, False, telegram_result

    payload = compute_weekly_beta_report_payload(db, week_start=week_start, week_end=week_end)
    now = datetime.now()
    created = existing is None
    if existing is None:
        row = WeeklyBetaReport(
            week_start=week_start,
            week_end=week_end,
            week_label=payload.current.week_label,
            payload_json=payload.model_dump_json(),
            telegram_status="pending",
            generated_at=now,
            generated_by=generated_by[:64],
        )
        db.add(row)
    else:
        row = existing
        row.payload_json = payload.model_dump_json()
        row.week_label = payload.current.week_label
        row.generated_at = now
        row.generated_by = generated_by[:64]
        row.telegram_status = "pending"
        row.telegram_error = None
        row.telegram_sent_at = None

    db.flush()

    telegram_result = {"skipped": True, "reason": "send_disabled"}
    if send_telegram:
        telegram_result = send_weekly_report_telegram(payload, settings=cfg)
        _apply_telegram_result(row, telegram_result)

    db.commit()
    db.refresh(row)
    return row, created, telegram_result


def _apply_telegram_result(row: WeeklyBetaReport, result: dict[str, Any]) -> None:
    if result.get("sent"):
        row.telegram_status = "sent"
        row.telegram_sent_at = datetime.now()
        row.telegram_error = None
        return
    if result.get("skipped"):
        row.telegram_status = "skipped"
        row.telegram_error = str(result.get("reason") or "skipped")[:500]
        return
    # Attempted but channel failed / missing.
    row.telegram_status = "failed"
    parts = [
        f"telegram={result.get('telegram')}",
        f"reason={result.get('reason')}",
    ]
    row.telegram_error = "; ".join(p for p in parts if p.split("=", 1)[-1] not in ("None",))[:500]
