"""Helpers to emit metrics / alerts from pipeline and ops checks."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.observability.alerts import send_admin_alert
from backend.src.app.observability.errors import capture_message
from backend.src.app.observability.metrics import record_counter, record_histogram
from backend.src.app.observability.ops_checks import failing_check_messages, run_ops_checks
from backend.src.entity.global_update_run import GlobalUpdateRun

logger = logging.getLogger(__name__)


def _alert_kwargs(settings: Settings) -> dict[str, Any]:
    return {
        "telegram_bot_token": settings.telegram_bot_token,
        "telegram_admin_chat_id": settings.telegram_admin_chat_id,
        "webhook_url": settings.ops_alert_webhook_url,
        "cooldown_seconds": settings.ops_alert_cooldown_seconds,
        "enabled": settings.ops_alerts_enabled,
    }


def notify_global_update_finished(run: GlobalUpdateRun, settings: Settings | None = None) -> None:
    """Record pipeline metrics and alert on non-success outcomes."""
    cfg = settings or get_settings()
    status = run.status or "unknown"
    record_counter(
        "pipeline_runs_total",
        labels={"status": status, "origin": run.origin or "unknown"},
    )
    if run.duration_seconds is not None:
        record_histogram(
            "pipeline_duration_seconds",
            float(run.duration_seconds),
            labels={"status": status},
        )

    if status in ("failed", "interrupted"):
        msg = (
            f"Global update run_id={run.id} status={status} "
            f"duration={run.duration_seconds}s failed={run.combinations_failed}"
        )
        capture_message(msg, level="error", context={"run_id": run.id, "status": status})
        send_admin_alert(
            msg,
            severity="critical",
            dedupe_key=f"pipeline:{status}:{run.id}",
            **_alert_kwargs(cfg),
        )
    elif status == "completed_with_errors":
        msg = (
            f"Global update run_id={run.id} completed_with_errors "
            f"failed_combos={run.combinations_failed} duration={run.duration_seconds}s"
        )
        capture_message(msg, level="warning", context={"run_id": run.id})
        send_admin_alert(
            msg,
            severity="warning",
            dedupe_key=f"pipeline:with_errors:{run.id}",
            **_alert_kwargs(cfg),
        )
    elif (
        run.duration_seconds is not None
        and run.duration_seconds > cfg.ops_pipeline_max_duration_seconds
    ):
        msg = (
            f"Global update run_id={run.id} durata anomala "
            f"{run.duration_seconds}s (soglia {cfg.ops_pipeline_max_duration_seconds}s)"
        )
        send_admin_alert(
            msg,
            severity="warning",
            dedupe_key=f"pipeline:duration:{run.id}",
            **_alert_kwargs(cfg),
        )


def run_and_alert_ops_checks(db: Session, settings: Settings | None = None) -> dict[str, Any]:
    """Execute ops checks and send a single aggregated alert if anything fails."""
    cfg = settings or get_settings()
    report = run_ops_checks(
        db,
        import_max_age_hours=cfg.ops_import_max_age_hours,
        predictions_lookback_hours=cfg.ops_predictions_lookback_hours,
        max_duration_seconds=cfg.ops_pipeline_max_duration_seconds,
        public_model_version=cfg.public_model_version,
        public_model_name=cfg.public_model_name,
    )
    record_counter("ops_checks_total", labels={"status": report["status"]})
    failures = failing_check_messages(report)
    if failures:
        severity = "critical" if report["status"] == "critical" else "warning"
        send_admin_alert(
            "Controlli operativi:\n- " + "\n- ".join(failures),
            severity=severity,
            dedupe_key=f"ops_checks:{report['status']}",
            **_alert_kwargs(cfg),
        )
        capture_message(
            f"ops_checks status={report['status']}",
            level="error" if severity == "critical" else "warning",
            context={"failures": failures},
        )
    return report
