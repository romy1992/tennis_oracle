"""Operational checks: import failure, missing predictions, anomalous duration."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.src.app.services.import_state import get_import_status
from backend.src.entity.global_update_run import GlobalUpdateRun
from backend.src.entity.match_prediction import MatchPrediction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpsCheckResult:
    name: str
    status: str  # ok | warning | critical
    message: str
    details: dict[str, Any]


def check_import_freshness(
    db: Session,
    *,
    max_age_hours: int = 36,
) -> OpsCheckResult:
    """Fail when next-fixture import is stale or fixtures import is too old."""
    status = get_import_status(db)
    now = datetime.now()
    issues: list[str] = []
    details: dict[str, Any] = {
        "next_fixtures_imported_today": status.get("next_fixtures_imported_today"),
        "next_fixtures_last_imported_at": (
            status["next_fixtures_last_imported_at"].isoformat()
            if status.get("next_fixtures_last_imported_at")
            else None
        ),
        "fixtures_last_imported_at": (
            status["fixtures_last_imported_at"].isoformat()
            if status.get("fixtures_last_imported_at")
            else None
        ),
        "max_age_hours": max_age_hours,
    }

    next_at = status.get("next_fixtures_last_imported_at")
    if next_at is None:
        issues.append("nessun import next_fixture registrato")
    else:
        age_h = (now - next_at).total_seconds() / 3600.0
        details["next_fixtures_age_hours"] = round(age_h, 2)
        if age_h > max_age_hours:
            issues.append(f"next_fixture import vecchio di {age_h:.1f}h (soglia {max_age_hours}h)")

    fixtures_at = status.get("fixtures_last_imported_at")
    if fixtures_at is not None:
        age_h = (now - fixtures_at).total_seconds() / 3600.0
        details["fixtures_age_hours"] = round(age_h, 2)
        if age_h > max_age_hours:
            issues.append(f"fixture import vecchio di {age_h:.1f}h (soglia {max_age_hours}h)")

    # Also flag recent failed/interrupted global updates that mention import.
    recent_failed = db.scalar(
        select(func.count())
        .select_from(GlobalUpdateRun)
        .where(
            GlobalUpdateRun.run_date >= date.today() - timedelta(days=1),
            GlobalUpdateRun.status.in_(("failed", "interrupted", "completed_with_errors")),
        )
    )
    details["recent_failed_runs"] = int(recent_failed or 0)

    if issues:
        level = "critical" if next_at is None else "warning"
        return OpsCheckResult(
            name="import_freshness",
            status=level,
            message="; ".join(issues),
            details=details,
        )
    return OpsCheckResult(
        name="import_freshness",
        status="ok",
        message="Import recenti entro soglia",
        details=details,
    )


def check_predictions_present(
    db: Session,
    *,
    model_version: str | None = None,
    model_name: str | None = None,
    lookback_hours: int = 36,
) -> OpsCheckResult:
    """Fail when no MatchPrediction rows were written recently."""
    since = datetime.now() - timedelta(hours=lookback_hours)
    stmt = select(func.count()).select_from(MatchPrediction).where(
        MatchPrediction.predicted_at >= since
    )
    if model_version:
        stmt = stmt.where(MatchPrediction.model_version == model_version)
    if model_name:
        stmt = stmt.where(MatchPrediction.model_name == model_name)
    count = int(db.scalar(stmt) or 0)
    details = {
        "count": count,
        "since": since.isoformat(),
        "lookback_hours": lookback_hours,
        "model_version": model_version,
        "model_name": model_name,
    }
    if count <= 0:
        return OpsCheckResult(
            name="predictions_present",
            status="critical",
            message=f"Nessun pronostico scritto nelle ultime {lookback_hours}h",
            details=details,
        )
    return OpsCheckResult(
        name="predictions_present",
        status="ok",
        message=f"{count} pronostici nelle ultime {lookback_hours}h",
        details=details,
    )


def check_pipeline_duration(
    db: Session,
    *,
    max_duration_seconds: int = 7200,
    lookback_days: int = 7,
) -> OpsCheckResult:
    """Flag runs whose duration exceeds the configured anomaly threshold."""
    since = date.today() - timedelta(days=lookback_days)
    runs = db.scalars(
        select(GlobalUpdateRun)
        .where(
            GlobalUpdateRun.run_date >= since,
            GlobalUpdateRun.duration_seconds.is_not(None),
            GlobalUpdateRun.status.in_(
                ("completed", "completed_with_errors", "failed", "interrupted", "cancelled")
            ),
        )
        .order_by(GlobalUpdateRun.id.desc())
        .limit(20)
    ).all()

    anomalous = [
        {
            "run_id": run.id,
            "status": run.status,
            "duration_seconds": run.duration_seconds,
            "run_date": run.run_date.isoformat() if run.run_date else None,
        }
        for run in runs
        if run.duration_seconds is not None and run.duration_seconds > max_duration_seconds
    ]
    latest = runs[0] if runs else None
    details: dict[str, Any] = {
        "max_duration_seconds": max_duration_seconds,
        "lookback_days": lookback_days,
        "examined": len(runs),
        "anomalous_count": len(anomalous),
        "anomalous": anomalous[:5],
        "latest_run_id": latest.id if latest else None,
        "latest_duration_seconds": latest.duration_seconds if latest else None,
    }
    if anomalous:
        return OpsCheckResult(
            name="pipeline_duration",
            status="warning",
            message=(
                f"{len(anomalous)} run oltre soglia {max_duration_seconds}s "
                f"(ultima: run_id={anomalous[0]['run_id']}, "
                f"{anomalous[0]['duration_seconds']}s)"
            ),
            details=details,
        )
    return OpsCheckResult(
        name="pipeline_duration",
        status="ok",
        message="Nessuna durata anomala recente",
        details=details,
    )


def check_latest_run_outcome(db: Session) -> OpsCheckResult:
    """Surface the latest global-update terminal status."""
    run = db.scalar(select(GlobalUpdateRun).order_by(GlobalUpdateRun.id.desc()).limit(1))
    if run is None:
        return OpsCheckResult(
            name="latest_run_outcome",
            status="warning",
            message="Nessuna global update run in database",
            details={},
        )
    details = {
        "run_id": run.id,
        "status": run.status,
        "run_date": run.run_date.isoformat() if run.run_date else None,
        "duration_seconds": run.duration_seconds,
        "combinations_failed": run.combinations_failed,
    }
    if run.status in ("failed", "interrupted"):
        return OpsCheckResult(
            name="latest_run_outcome",
            status="critical",
            message=f"Ultima run {run.id} in stato {run.status}",
            details=details,
        )
    if run.status == "completed_with_errors":
        return OpsCheckResult(
            name="latest_run_outcome",
            status="warning",
            message=f"Ultima run {run.id} completed_with_errors",
            details=details,
        )
    if run.status in ("running", "pending", "cancelling"):
        return OpsCheckResult(
            name="latest_run_outcome",
            status="ok",
            message=f"Ultima run {run.id} ancora in corso ({run.status})",
            details=details,
        )
    return OpsCheckResult(
        name="latest_run_outcome",
        status="ok",
        message=f"Ultima run {run.id} status={run.status}",
        details=details,
    )


def run_ops_checks(
    db: Session,
    *,
    import_max_age_hours: int = 36,
    predictions_lookback_hours: int = 36,
    max_duration_seconds: int = 7200,
    public_model_version: str | None = None,
    public_model_name: str | None = None,
) -> dict[str, Any]:
    """Execute all operational checks and return a summary payload."""
    checks = [
        check_import_freshness(db, max_age_hours=import_max_age_hours),
        check_predictions_present(
            db,
            model_version=public_model_version,
            model_name=public_model_name,
            lookback_hours=predictions_lookback_hours,
        ),
        check_pipeline_duration(db, max_duration_seconds=max_duration_seconds),
        check_latest_run_outcome(db),
    ]
    statuses = {c.status for c in checks}
    if "critical" in statuses:
        overall = "critical"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "ok"
    return {
        "status": overall,
        "checked_at": datetime.now().isoformat(),
        "checks": [asdict(c) for c in checks],
    }


def failing_check_messages(report: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for check in report.get("checks") or []:
        if check.get("status") in ("warning", "critical"):
            messages.append(f"{check.get('name')}: {check.get('message')}")
    return messages
