"""Daily update and Monday walk-forward/calibration scheduling services."""

from __future__ import annotations

import json
import logging
import os
import socket
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings
from backend.src.app.observability.email_reports import EmailAttachment, send_report_email
from backend.src.app.schemas.calibration import CalibrationTriggerRequest
from backend.src.app.schemas.walk_forward import WalkForwardTriggerRequest
from backend.src.app.services.calibration import start_calibration_run
from backend.src.app.services.global_update import start_global_update
from backend.src.app.services.walk_forward import start_walk_forward_run
from backend.src.entity.calibration import CalibrationRun
from backend.src.entity.global_update_run import GlobalUpdateRun
from backend.src.entity.scheduled_report_job import ScheduledReportJob
from backend.src.entity.walk_forward import WalkForwardRun
from backend.src.utility.sensitive_data import sanitize_text

DAILY_JOB_NAME = "daily_global_update"
WEEKLY_JOB_NAME = "weekly_validation"
TERMINAL_GLOBAL_UPDATE_STATUSES = {
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
    "interrupted",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobSource:
    environment: str
    name: str
    url: str | None
    hostname: str
    path: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "environment": self.environment,
            "name": self.name,
            "url": self.url,
            "hostname": self.hostname,
            "path": self.path,
        }


def resolve_job_source(settings: Settings) -> JobSource:
    environment = (settings.app_env or "unknown").strip()
    return JobSource(
        environment=environment,
        name=(settings.scheduled_job_source_name or f"tennis-oracle-{environment}").strip(),
        url=(settings.scheduled_job_source_url or "").strip() or None,
        hostname=socket.gethostname(),
        path=(settings.scheduled_job_source_path or str(Path.cwd().resolve())).strip(),
    )


def parse_schedule_time(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Orario pianificato non valido: {value}")
    hour, minute = (int(part) for part in parts)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Orario pianificato non valido: {value}")
    return time(hour=hour, minute=minute)


def scheduled_for_utc(
    scheduled_date: date,
    clock: str,
    timezone_name: str,
) -> datetime:
    local = datetime.combine(scheduled_date, parse_schedule_time(clock), ZoneInfo(timezone_name))
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _schedule_key(job_name: str, scheduled_date: date) -> str:
    return f"{job_name}:{scheduled_date.isoformat()}"


def get_scheduled_job(
    db: Session,
    job_name: str,
    scheduled_date: date,
) -> ScheduledReportJob | None:
    return db.scalar(
        select(ScheduledReportJob).where(
            ScheduledReportJob.schedule_key == _schedule_key(job_name, scheduled_date)
        )
    )


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=_json_default)


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def claim_schedule(
    db: Session,
    *,
    job_name: str,
    scheduled_for: datetime,
    scheduled_date: date,
    source: JobSource,
) -> tuple[ScheduledReportJob, bool]:
    """Atomically claim one date slot; a unique key resolves cross-worker races."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = ScheduledReportJob(
        schedule_key=_schedule_key(job_name, scheduled_date),
        job_name=job_name,
        scheduled_for=scheduled_for,
        status="pending",
        source_environment=source.environment,
        source_name=source.name,
        source_url=source.url,
        source_hostname=source.hostname,
        source_path=source.path,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row, True
    except IntegrityError:
        db.rollback()
        existing = get_scheduled_job(db, job_name, scheduled_date)
        if existing is None:  # Defensive: a non-key integrity error should not be hidden.
            raise
        return existing, False


def _mark_running(db: Session, job: ScheduledReportJob) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    job.status = "running"
    job.started_at = now
    job.updated_at = now
    db.commit()


def _persist_job_report(
    db: Session,
    job: ScheduledReportJob,
    *,
    status: str,
    message: str,
    report: dict[str, Any],
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    job.status = status
    job.message = sanitize_text(message, max_length=4000)
    job.report_json = _json_dumps(report)
    job.finished_at = now
    job.updated_at = now
    db.commit()


def _persist_email_result(
    db: Session,
    job: ScheduledReportJob,
    result: dict[str, Any],
) -> None:
    job.email_status = str(result.get("status") or "unknown")
    error = result.get("error")
    job.email_error = sanitize_text(str(error), max_length=1000) if error else None
    job.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()


def _source_lines(source: JobSource) -> list[str]:
    return [
        f"Ambiente: {source.environment}",
        f"Sorgente: {source.name}",
        f"URL sorgente: {source.url or '-'}",
        f"Hostname runtime: {source.hostname}",
        f"Path runtime: {source.path}",
    ]


def _entity_payload(row: Any | None) -> dict[str, Any] | None:
    return row.to_dict() if row is not None else None


def _json_attachment(filename: str, payload: dict[str, Any]) -> EmailAttachment:
    return EmailAttachment(filename=filename, content=_json_dumps(payload).encode("utf-8"))


def _path_attachment(path: str | None) -> EmailAttachment | None:
    if not path:
        return None
    return EmailAttachment.from_path(path)


def _latest_global_for_date(db: Session, scheduled_date: date) -> GlobalUpdateRun | None:
    return db.scalar(
        select(GlobalUpdateRun)
        .where(GlobalUpdateRun.run_date == scheduled_date)
        .order_by(GlobalUpdateRun.id.desc())
        .limit(1)
    )


def list_stale_daily_report_dates(
    db: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
    limit: int = 31,
) -> list[date]:
    """Return old daily report slots eligible for a guarded recovery attempt."""
    current = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    recovery_seconds = max(60, int(settings.scheduled_reports_recovery_seconds))
    stale_before = current - timedelta(seconds=recovery_seconds)
    scheduled_values = db.scalars(
        select(ScheduledReportJob.scheduled_for)
        .where(
            ScheduledReportJob.job_name == DAILY_JOB_NAME,
            ScheduledReportJob.status == "running",
            ScheduledReportJob.email_status.is_(None),
            ScheduledReportJob.updated_at <= stale_before,
        )
        .order_by(ScheduledReportJob.scheduled_for)
        .limit(max(1, limit))
    ).all()
    local_timezone = ZoneInfo(settings.scheduled_reports_timezone)
    return [
        value.replace(tzinfo=timezone.utc).astimezone(local_timezone).date()
        for value in scheduled_values
    ]


def _reclaim_stale_daily_report(
    db: Session,
    settings: Settings,
    *,
    job: ScheduledReportJob,
    scheduled_date: date,
    source: JobSource,
) -> GlobalUpdateRun | None:
    """Reclaim only a stale report whose global update is already terminal.

    This recovers a worker that died after completing the expensive update but
    before persisting/sending its report.  It deliberately never starts a
    second update while the first one may still be active.
    """
    if job.status != "running" or job.email_status is not None:
        return None

    recovery_seconds = max(60, int(settings.scheduled_reports_recovery_seconds))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stale_before = now - timedelta(seconds=recovery_seconds)
    if job.updated_at is None or job.updated_at > stale_before:
        return None

    run = _latest_global_for_date(db, scheduled_date)
    if run is None or run.status not in TERMINAL_GLOBAL_UPDATE_STATUSES:
        return None

    result = db.execute(
        update(ScheduledReportJob)
        .where(
            ScheduledReportJob.id == job.id,
            ScheduledReportJob.status == "running",
            ScheduledReportJob.email_status.is_(None),
            ScheduledReportJob.updated_at <= stale_before,
        )
        .values(
            status="pending",
            source_environment=source.environment,
            source_name=source.name,
            source_url=source.url,
            source_hostname=source.hostname,
            source_path=source.path,
            global_update_run_id=run.id,
            message=None,
            report_json=None,
            email_error=None,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )
    )
    db.commit()
    if result.rowcount == 1:
        db.refresh(job)
        logger.warning(
            "Reclaimed stale scheduled daily report job_id=%s run_id=%s age_seconds>=%s "
            "source=%s",
            job.id,
            run.id,
            recovery_seconds,
            source.name,
        )
        return run
    return None


def _daily_report_payload(
    *,
    job: ScheduledReportJob,
    source: JobSource,
    run: GlobalUpdateRun | None,
    message: str,
) -> dict[str, Any]:
    return {
        "job": {
            "id": job.id,
            "schedule_key": job.schedule_key,
            "scheduled_for": job.scheduled_for,
            "message": message,
        },
        "source": source.to_dict(),
        "global_update": _entity_payload(run),
        "global_update_report": _json_loads(run.report_json) if run else None,
        "global_update_errors": _json_loads(run.errors_json) if run else None,
        "global_update_warnings": _json_loads(run.warnings_json) if run else None,
    }


def run_daily_scheduled_report(
    db: Session,
    settings: Settings,
    *,
    scheduled_date: date,
    source: JobSource | None = None,
    global_update_starter: Callable[..., tuple[GlobalUpdateRun | None, str]] = start_global_update,
) -> tuple[ScheduledReportJob, bool]:
    """Run/observe the date's global update and email its operational report."""
    source = source or resolve_job_source(settings)
    scheduled_for = scheduled_for_utc(
        scheduled_date,
        settings.scheduled_global_update_time,
        settings.scheduled_reports_timezone,
    )
    job, claimed = claim_schedule(
        db,
        job_name=DAILY_JOB_NAME,
        scheduled_for=scheduled_for,
        scheduled_date=scheduled_date,
        source=source,
    )
    recovered_run: GlobalUpdateRun | None = None
    if not claimed:
        recovered_run = _reclaim_stale_daily_report(
            db,
            settings,
            job=job,
            scheduled_date=scheduled_date,
            source=source,
        )
        if recovered_run is None:
            return job, False
        claimed = True

    _mark_running(db, job)
    run: GlobalUpdateRun | None = recovered_run
    message = (
        f"Recovered stale scheduled report for terminal run_id={recovered_run.id}."
        if recovered_run is not None
        else ""
    )
    try:
        if recovered_run is None:
            run, message = global_update_starter(
                db,
                origin="job",
                force=False,
                days_forward=10,
                days_back_fixtures=3,
                sync_cloud=_env_flag("SYNC_CLOUD", default=False),
                blocking=True,
            )
        db.expire_all()
        if run is None:
            run = _latest_global_for_date(db, scheduled_date)
        if run is not None:
            job.global_update_run_id = run.id

        status = run.status if run is not None else "failed"
        if status not in {"completed", "completed_with_errors", "failed", "cancelled"}:
            status = "failed"
        report = _daily_report_payload(job=job, source=source, run=run, message=message)
        _persist_job_report(db, job, status=status, message=message or status, report=report)
    except Exception as exc:
        message = sanitize_text(f"{type(exc).__name__}: {exc}", max_length=1000)
        report = _daily_report_payload(job=job, source=source, run=run, message=message)
        _persist_job_report(db, job, status="failed", message=message, report=report)

    run_status = run.status if run is not None else "non avviato"
    body = "\n".join(
        [
            "Report pianificato: Aggiorna tutto",
            f"Data pianificata: {scheduled_date.isoformat()}",
            f"Esito: {run_status}",
            f"Global update run ID: {run.id if run else '-'}",
            f"Durata secondi: {run.duration_seconds if run else '-'}",
            f"Messaggio: {message or '-'}",
            "",
            "Provenienza del job:",
            *_source_lines(source),
        ]
    )
    attachment_payload = _daily_report_payload(job=job, source=source, run=run, message=message)
    email_result = send_report_email(
        settings,
        subject=(
            f"[tennis_oracle][{source.environment}] Aggiorna tutto "
            f"{scheduled_date.isoformat()} - {run_status}"
        ),
        body=body,
        attachments=(
            _json_attachment(
                f"global_update_{scheduled_date.isoformat()}_{source.environment}.json",
                attachment_payload,
            ),
        ),
    )
    _persist_email_result(db, job, email_result)
    return job, True


def _daily_gate(
    db: Session,
    scheduled_date: date,
) -> tuple[ScheduledReportJob | None, GlobalUpdateRun | None, str]:
    daily_job = get_scheduled_job(db, DAILY_JOB_NAME, scheduled_date)
    if daily_job is None:
        return None, None, "Aggiorna tutto delle 08:00 non risulta eseguito."
    if daily_job.global_update_run_id is None:
        return daily_job, None, "Aggiorna tutto delle 08:00 non ha una run associata."
    run = db.get(GlobalUpdateRun, daily_job.global_update_run_id)
    if run is None:
        return daily_job, None, "La run di Aggiorna tutto associata non esiste più."
    if run.status != "completed":
        return daily_job, run, f"Aggiorna tutto non è completato con successo: {run.status}."
    return daily_job, run, "Aggiorna tutto completato con successo."


def _weekly_payload(
    *,
    job: ScheduledReportJob,
    source: JobSource,
    daily_job: ScheduledReportJob | None,
    global_run: GlobalUpdateRun | None,
    walk_forward_run: WalkForwardRun | None,
    calibration_run: CalibrationRun | None,
    message: str,
) -> dict[str, Any]:
    return {
        "job": {
            "id": job.id,
            "schedule_key": job.schedule_key,
            "scheduled_for": job.scheduled_for,
            "message": message,
        },
        "source": source.to_dict(),
        "daily_schedule": _entity_payload(daily_job),
        "global_update": _entity_payload(global_run),
        "walk_forward": _entity_payload(walk_forward_run),
        "walk_forward_summary": (
            _json_loads(walk_forward_run.summary_json) if walk_forward_run else None
        ),
        "calibration": _entity_payload(calibration_run),
        "calibration_summary": (
            _json_loads(calibration_run.summary_json) if calibration_run else None
        ),
    }


def calibration_model_error_lines(summary: Any) -> list[str]:
    """Human-readable extra-market/model failures stored on a calibration run."""
    if not isinstance(summary, dict):
        return []
    lines: list[str] = []
    details = summary.get("models_detail")
    if not isinstance(details, list):
        details = []
    for item in details:
        if not isinstance(item, dict):
            continue
        flags = item.get("leakage_flags") or []
        comparison = item.get("comparison") if isinstance(item.get("comparison"), dict) else {}
        error = comparison.get("error")
        if not flags and not error:
            continue
        detail = error or flags[0]
        version = item.get("model_version") or "?"
        model_name = item.get("model_name") or "?"
        lines.append(f"- {version}/{model_name}: {detail}")
    return lines


def _calibration_request_for_walk_forward(
    run: WalkForwardRun,
    settings: Settings,
) -> CalibrationTriggerRequest:
    versions = [part.strip() for part in run.versions_requested.split(",") if part.strip()]
    return CalibrationTriggerRequest(
        n_bins=settings.calibration_n_bins,
        min_bin_samples=settings.calibration_min_bin_samples,
        min_calibrator_train_samples=settings.calibration_min_calibrator_train_samples,
        mode=run.mode,  # type: ignore[arg-type]
        initial_train_days=run.initial_train_days,
        test_days=run.test_days,
        step_days=run.step_days,
        min_train_rows=run.min_train_rows,
        min_test_rows=run.min_test_rows,
        embargo_days=run.embargo_days,
        edge_threshold=run.edge_threshold,
        random_state=run.random_state,
        versions=versions,  # type: ignore[arg-type]
        walk_forward_run_id=run.id,
        blocking=True,
    )


def run_weekly_scheduled_report(
    db: Session,
    settings: Settings,
    *,
    scheduled_date: date,
    source: JobSource | None = None,
    walk_forward_starter: Callable[..., tuple[WalkForwardRun, bool, str]] = (
        start_walk_forward_run
    ),
    calibration_starter: Callable[..., tuple[CalibrationRun, bool, str]] = start_calibration_run,
) -> tuple[ScheduledReportJob, bool]:
    """Run strict global-update -> walk-forward -> calibration cascade."""
    source = source or resolve_job_source(settings)
    scheduled_for = scheduled_for_utc(
        scheduled_date,
        settings.scheduled_weekly_validation_time,
        settings.scheduled_reports_timezone,
    )
    job, claimed = claim_schedule(
        db,
        job_name=WEEKLY_JOB_NAME,
        scheduled_for=scheduled_for,
        scheduled_date=scheduled_date,
        source=source,
    )
    if not claimed:
        return job, False

    _mark_running(db, job)
    daily_job, global_run, gate_message = _daily_gate(db, scheduled_date)
    walk_forward_run: WalkForwardRun | None = None
    calibration_run: CalibrationRun | None = None
    final_status = "skipped"
    message = gate_message

    if global_run is not None and global_run.status == "completed":
        try:
            wf_request = WalkForwardTriggerRequest(blocking=True)
            walk_forward_run, wf_started, wf_message = walk_forward_starter(
                db,
                request=wf_request,
                settings=settings,
                origin="job",
                created_by=f"scheduler:{source.name}"[:64],
                blocking=True,
            )
            job.walk_forward_run_id = walk_forward_run.id
            db.commit()
            if not wf_started or walk_forward_run.status != "completed":
                final_status = "failed"
                message = (
                    "Calibrazione non avviata: walk-forward non completato con successo "
                    f"(status={walk_forward_run.status}, started={wf_started}). {wf_message}"
                )
            else:
                calibration_request = _calibration_request_for_walk_forward(
                    walk_forward_run,
                    settings,
                )
                calibration_run, calibration_started, calibration_message = calibration_starter(
                    db,
                    request=calibration_request,
                    settings=settings,
                    origin="job",
                    created_by=f"scheduler:{source.name}"[:64],
                    blocking=True,
                )
                job.calibration_run_id = calibration_run.id
                db.commit()
                if calibration_started and calibration_run.status == "completed":
                    final_status = "completed"
                    message = "Walk-forward e calibrazione completati con successo."
                else:
                    final_status = "failed"
                    message = (
                        "Calibrazione non completata con successo "
                        f"(status={calibration_run.status}, started={calibration_started}). "
                        f"{calibration_message}"
                    )
        except Exception as exc:
            final_status = "failed"
            message = sanitize_text(f"{type(exc).__name__}: {exc}", max_length=1000)

    if global_run is not None:
        job.global_update_run_id = global_run.id
    report = _weekly_payload(
        job=job,
        source=source,
        daily_job=daily_job,
        global_run=global_run,
        walk_forward_run=walk_forward_run,
        calibration_run=calibration_run,
        message=message,
    )
    _persist_job_report(db, job, status=final_status, message=message, report=report)

    calibration_error_lines = calibration_model_error_lines(
        _json_loads(calibration_run.summary_json) if calibration_run else None
    )
    body_lines = [
        "Report pianificato: doppietta Walk-forward + Calibrazione",
        f"Data pianificata: {scheduled_date.isoformat()}",
        f"Esito cascata: {final_status}",
        f"Aggiorna tutto run ID/status: {global_run.id if global_run else '-'} / "
        f"{global_run.status if global_run else '-'}",
        f"Walk-forward run ID/status: {walk_forward_run.id if walk_forward_run else '-'} / "
        f"{walk_forward_run.status if walk_forward_run else 'non avviato'}",
        f"Calibrazione run ID/status: {calibration_run.id if calibration_run else '-'} / "
        f"{calibration_run.status if calibration_run else 'non avviata'}",
        f"Messaggio: {message}",
    ]
    if calibration_error_lines:
        body_lines.append("Errori modelli calibrazione:")
        body_lines.extend(calibration_error_lines)
    body_lines.extend(["", "Provenienza del job:", *_source_lines(source)])
    body = "\n".join(body_lines)
    attachments: list[EmailAttachment] = [
        _json_attachment(
            f"weekly_validation_{scheduled_date.isoformat()}_{source.environment}.json",
            report,
        )
    ]
    for path in (
        walk_forward_run.report_path if walk_forward_run else None,
        calibration_run.report_path if calibration_run else None,
    ):
        attachment = _path_attachment(path)
        if attachment is not None:
            attachments.append(attachment)

    email_result = send_report_email(
        settings,
        subject=(
            f"[tennis_oracle][{source.environment}] Walk-forward + Calibrazione "
            f"{scheduled_date.isoformat()} - {final_status}"
        ),
        body=body,
        attachments=attachments,
    )
    _persist_email_result(db, job, email_result)
    return job, True
