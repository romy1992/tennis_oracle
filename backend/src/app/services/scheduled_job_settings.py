"""Catalog and runtime overlay for admin-managed scheduler jobs."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.schemas.settings import ScheduledJobRead
from backend.src.app.services.scheduled_reports import parse_schedule_time
from backend.src.entity.scheduled_job_setting import ScheduledJobSetting

logger = logging.getLogger(__name__)

ScheduleKind = Literal["clock", "weekly_clock", "interval"]
ScheduleSource = Literal["database", "environment"]
ScheduledJobWorker = Literal["report_scheduler", "api_scheduler"]

DAILY_JOB_KEY = "daily_global_update"
WEEKLY_JOB_KEY = "weekly_validation"
LIVE_POLL_JOB_KEY = "betting_slip_live_poll"
RECAP_JOB_KEY = "betting_slip_recap"
TELEGRAM_JOB_KEY = "telegram_notifications"
WEEKLY_BETA_JOB_KEY = "weekly_beta_report"
CLOSING_ODDS_JOB_KEY = "closing_odds_capture"
OPS_CHECKS_JOB_KEY = "ops_checks"
DB_BACKUP_JOB_KEY = "db_backup"

AUXILIARY_JOB_KEYS: tuple[str, ...] = (
    TELEGRAM_JOB_KEY,
    WEEKLY_BETA_JOB_KEY,
    CLOSING_ODDS_JOB_KEY,
    OPS_CHECKS_JOB_KEY,
    DB_BACKUP_JOB_KEY,
)

RUNNING_STALE_AFTER = timedelta(hours=6)


class ScheduledJobSettingsError(Exception):
    """Domain error for scheduled job settings."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class JobDefinition:
    key: str
    label: str
    description: str
    badge: str | None
    worker: ScheduledJobWorker
    schedule_kind: ScheduleKind
    default_clock_time: str | None = None
    default_weekday: int | None = None
    default_interval_seconds: int | None = None
    min_interval_seconds: int | None = None
    enabled_setting: str | None = None


@dataclass(frozen=True)
class EffectiveSchedule:
    job_key: str
    enabled: bool
    schedule_kind: ScheduleKind
    clock_time: str | None
    weekday: int | None
    interval_seconds: int | None
    source: ScheduleSource
    last_run_at: datetime | None
    last_run_status: str | None
    updated_at: datetime | None
    updated_by: str | None


JOB_CATALOG: tuple[JobDefinition, ...] = (
    JobDefinition(
        key=DAILY_JOB_KEY,
        label="Aggiorna tutto",
        description=(
            "Esegue la pipeline giornaliera (import, previsioni, schedine e pubblicazione) "
            "e invia il report email. Gestito dal worker report-scheduler."
        ),
        badge="Pipeline",
        worker="report_scheduler",
        schedule_kind="clock",
        default_clock_time="08:00",
        enabled_setting="scheduled_reports_enabled",
    ),
    JobDefinition(
        key=WEEKLY_JOB_KEY,
        label="Walk-forward + Calibrazione",
        description=(
            "Ogni settimana, dopo l'orario impostato, avvia walk-forward e calibrazione "
            "solo se Aggiorna tutto dello stesso giorno è completed, poi invia il report."
        ),
        badge="ML",
        worker="report_scheduler",
        schedule_kind="weekly_clock",
        default_clock_time="10:00",
        default_weekday=0,
        enabled_setting="scheduled_reports_enabled",
    ),
    JobDefinition(
        key=LIVE_POLL_JOB_KEY,
        label="Polling live schedine",
        description=(
            "Aggiorna i punteggi live delle schedine del giorno. Gira nel processo API."
        ),
        badge="API",
        worker="api_scheduler",
        schedule_kind="interval",
        default_interval_seconds=180,
        min_interval_seconds=30,
        enabled_setting="betting_slip_live_poll_enabled",
    ),
    JobDefinition(
        key=RECAP_JOB_KEY,
        label="Recap schedine Telegram",
        description=(
            "Invia il recap giornaliero delle schedine su Telegram. Gira nel processo API."
        ),
        badge="Telegram",
        worker="api_scheduler",
        schedule_kind="clock",
        default_clock_time="23:30",
        enabled_setting="betting_slip_recap_enabled",
    ),
    JobDefinition(
        key=TELEGRAM_JOB_KEY,
        label="Notifiche Telegram utenti",
        description=(
            "Invia previsioni, risultati e giorno vuoto agli utenti Telegram abilitati."
        ),
        badge="Telegram",
        worker="report_scheduler",
        schedule_kind="clock",
        default_clock_time="08:30",
        enabled_setting="telegram_notifications_enabled",
    ),
    JobDefinition(
        key=WEEKLY_BETA_JOB_KEY,
        label="Report settimanale beta",
        description=(
            "Genera e salva il report beta della settimana precedente e notifica l'admin."
        ),
        badge="Beta",
        worker="report_scheduler",
        schedule_kind="weekly_clock",
        default_clock_time="08:30",
        default_weekday=0,
        enabled_setting=None,
    ),
    JobDefinition(
        key=CLOSING_ODDS_JOB_KEY,
        label="Cattura closing odds",
        description=(
            "Cattura le quote closing prima del kickoff. Serve un intervallo frequente "
            "(1-5 minuti) per una copertura CLV utile."
        ),
        badge="API-Tennis",
        worker="report_scheduler",
        schedule_kind="interval",
        default_interval_seconds=300,
        min_interval_seconds=10,
        enabled_setting="closing_odds_job_enabled",
    ),
    JobDefinition(
        key=OPS_CHECKS_JOB_KEY,
        label="Controlli operativi",
        description=(
            "Esegue i check su import, previsioni e durata pipeline e invia alert admin."
        ),
        badge="Ops",
        worker="report_scheduler",
        schedule_kind="clock",
        default_clock_time="08:20",
        enabled_setting="ops_alerts_enabled",
    ),
    JobDefinition(
        key=DB_BACKUP_JOB_KEY,
        label="Backup PostgreSQL",
        description=(
            "Dump logico del database con retention. Richiede pg_dump sull'host del worker."
        ),
        badge="DB",
        worker="report_scheduler",
        schedule_kind="clock",
        default_clock_time="03:30",
        enabled_setting=None,
    ),
)


def job_catalog_by_key() -> dict[str, JobDefinition]:
    return {item.key: item for item in JOB_CATALOG}


def get_job_definition(job_key: str) -> JobDefinition:
    definition = job_catalog_by_key().get((job_key or "").strip())
    if definition is None:
        raise ScheduledJobSettingsError(
            f"Job non supportato: {job_key}", status_code=404
        )
    return definition


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _env_enabled(settings: Settings, definition: JobDefinition) -> bool:
    if not definition.enabled_setting:
        return False
    return bool(getattr(settings, definition.enabled_setting))


def _env_clock_time(settings: Settings, definition: JobDefinition) -> str | None:
    if definition.key == DAILY_JOB_KEY:
        return settings.scheduled_global_update_time
    if definition.key == WEEKLY_JOB_KEY:
        return settings.scheduled_weekly_validation_time
    if definition.key == RECAP_JOB_KEY:
        return settings.betting_slip_recap_time
    return definition.default_clock_time


def _env_weekday(settings: Settings, definition: JobDefinition) -> int | None:
    if definition.key == WEEKLY_JOB_KEY:
        return settings.scheduled_weekly_validation_day
    return definition.default_weekday


def _env_interval_seconds(settings: Settings, definition: JobDefinition) -> int | None:
    if definition.key == LIVE_POLL_JOB_KEY:
        return max(
            definition.min_interval_seconds or 1,
            int(settings.betting_slip_live_poll_interval_seconds),
        )
    return definition.default_interval_seconds


def _load_setting_row(db: Session, job_key: str) -> ScheduledJobSetting | None:
    try:
        row = db.get(ScheduledJobSetting, job_key)
    except Exception:
        return None
    if isinstance(row, ScheduledJobSetting):
        return row
    return None


def get_effective_schedule(
    db: Session, settings: Settings, job_key: str
) -> EffectiveSchedule:
    definition = get_job_definition(job_key)
    row = _load_setting_row(db, job_key)
    if row is not None:
        return EffectiveSchedule(
            job_key=definition.key,
            enabled=bool(row.enabled),
            schedule_kind=definition.schedule_kind,
            clock_time=row.clock_time or _env_clock_time(settings, definition),
            weekday=(
                row.weekday
                if row.weekday is not None
                else _env_weekday(settings, definition)
            ),
            interval_seconds=(
                row.interval_seconds
                if row.interval_seconds is not None
                else _env_interval_seconds(settings, definition)
            ),
            source="database",
            last_run_at=row.last_run_at,
            last_run_status=row.last_run_status,
            updated_at=row.updated_at,
            updated_by=row.updated_by,
        )
    return EffectiveSchedule(
        job_key=definition.key,
        enabled=_env_enabled(settings, definition),
        schedule_kind=definition.schedule_kind,
        clock_time=_env_clock_time(settings, definition),
        weekday=_env_weekday(settings, definition),
        interval_seconds=_env_interval_seconds(settings, definition),
        source="environment",
        last_run_at=None,
        last_run_status=None,
        updated_at=None,
        updated_by=None,
    )


def to_scheduled_job_read(
    definition: JobDefinition, overlay: EffectiveSchedule
) -> ScheduledJobRead:
    return ScheduledJobRead(
        job_key=definition.key,
        label=definition.label,
        description=definition.description,
        badge=definition.badge,
        worker=definition.worker,
        schedule_kind=definition.schedule_kind,
        enabled=overlay.enabled,
        clock_time=overlay.clock_time,
        weekday=overlay.weekday,
        interval_seconds=overlay.interval_seconds,
        min_interval_seconds=definition.min_interval_seconds,
        source=overlay.source,
        last_run_at=overlay.last_run_at,
        last_run_status=overlay.last_run_status,
        updated_at=overlay.updated_at,
        updated_by=overlay.updated_by,
    )


def list_scheduled_jobs(db: Session, settings: Settings) -> list[ScheduledJobRead]:
    items: list[ScheduledJobRead] = []
    for definition in JOB_CATALOG:
        overlay = get_effective_schedule(db, settings, definition.key)
        items.append(to_scheduled_job_read(definition, overlay))
    return items


def _normalize_clock_time(value: str | None) -> str:
    if value is None or not str(value).strip():
        raise ScheduledJobSettingsError("Orario obbligatorio.", status_code=422)
    try:
        parsed = parse_schedule_time(str(value))
    except ValueError as exc:
        raise ScheduledJobSettingsError(str(exc), status_code=422) from exc
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def update_scheduled_job(
    db: Session,
    settings: Settings,
    *,
    job_key: str,
    enabled: bool | None = None,
    clock_time: str | None = None,
    weekday: int | None = None,
    interval_seconds: int | None = None,
    updated_by: str | None = None,
    commit: bool = True,
) -> ScheduledJobRead:
    definition = get_job_definition(job_key)
    overlay = get_effective_schedule(db, settings, job_key)
    row = _load_setting_row(db, job_key)
    now = _utc_now_naive()

    next_enabled = overlay.enabled if enabled is None else bool(enabled)
    next_clock = overlay.clock_time
    next_weekday = overlay.weekday
    next_interval = overlay.interval_seconds

    if clock_time is not None:
        if definition.schedule_kind == "interval":
            raise ScheduledJobSettingsError(
                "Questo job usa un intervallo, non un orario.", status_code=422
            )
        next_clock = _normalize_clock_time(clock_time)
    if weekday is not None:
        if definition.schedule_kind != "weekly_clock":
            raise ScheduledJobSettingsError(
                "Il giorno della settimana vale solo per i job settimanali.",
                status_code=422,
            )
        next_weekday = int(weekday)
    if interval_seconds is not None:
        if definition.schedule_kind != "interval":
            raise ScheduledJobSettingsError(
                "Questo job usa un orario, non un intervallo.", status_code=422
            )
        minimum = definition.min_interval_seconds or 1
        if interval_seconds < minimum:
            raise ScheduledJobSettingsError(
                f"Intervallo minimo: {minimum} secondi.", status_code=422
            )
        next_interval = int(interval_seconds)

    if definition.schedule_kind in {"clock", "weekly_clock"}:
        next_clock = _normalize_clock_time(next_clock)
    if definition.schedule_kind == "weekly_clock":
        if next_weekday is None or not (0 <= int(next_weekday) <= 6):
            raise ScheduledJobSettingsError(
                "Giorno della settimana non valido (0=lunedì … 6=domenica).",
                status_code=422,
            )
        next_weekday = int(next_weekday)
    if definition.schedule_kind == "interval":
        if next_interval is None:
            raise ScheduledJobSettingsError("Intervallo obbligatorio.", status_code=422)
        next_interval = int(next_interval)

    if row is None:
        row = ScheduledJobSetting(
            job_key=definition.key,
            enabled=next_enabled,
            schedule_kind=definition.schedule_kind,
            clock_time=next_clock,
            weekday=next_weekday,
            interval_seconds=next_interval,
            last_run_at=None,
            last_run_status=None,
            updated_at=now,
            updated_by=updated_by,
        )
        db.add(row)
    else:
        row.enabled = next_enabled
        row.schedule_kind = definition.schedule_kind
        row.clock_time = next_clock
        row.weekday = next_weekday
        row.interval_seconds = next_interval
        row.updated_at = now
        row.updated_by = updated_by

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()

    return to_scheduled_job_read(
        definition, get_effective_schedule(db, settings, definition.key)
    )


def ensure_setting_row(
    db: Session, settings: Settings, job_key: str
) -> ScheduledJobSetting | None:
    definition = get_job_definition(job_key)
    row = _load_setting_row(db, job_key)
    if row is not None:
        return row
    overlay = get_effective_schedule(db, settings, job_key)
    try:
        row = ScheduledJobSetting(
            job_key=definition.key,
            enabled=overlay.enabled,
            schedule_kind=definition.schedule_kind,
            clock_time=overlay.clock_time,
            weekday=overlay.weekday,
            interval_seconds=overlay.interval_seconds,
            last_run_at=None,
            last_run_status=None,
            updated_at=_utc_now_naive(),
            updated_by="scheduler",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return _load_setting_row(db, job_key)
    return row if isinstance(row, ScheduledJobSetting) else None


def mark_job_run(
    db: Session,
    settings: Settings,
    job_key: str,
    status: str,
    *,
    when: datetime | None = None,
) -> None:
    row = ensure_setting_row(db, settings, job_key)
    if row is None:
        return
    stamp = when or _utc_now_naive()
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    row.last_run_at = stamp
    row.last_run_status = status
    try:
        db.commit()
    except Exception:
        logger.exception("scheduled_job mark_run failed job=%s", job_key)
        try:
            db.rollback()
        except Exception:
            pass


def _already_ran_on_local_date(
    overlay: EffectiveSchedule, local_date, tz: ZoneInfo
) -> bool:
    if overlay.last_run_at is None:
        return False
    return _aware(overlay.last_run_at).astimezone(tz).date() == local_date


def _is_currently_running(overlay: EffectiveSchedule, now: datetime) -> bool:
    if overlay.last_run_status != "running" or overlay.last_run_at is None:
        return False
    last = _aware(overlay.last_run_at)
    current = _aware(now)
    return (current - last) < RUNNING_STALE_AFTER


def _interval_due(overlay: EffectiveSchedule, now: datetime) -> bool:
    interval = overlay.interval_seconds or 0
    if interval <= 0:
        return False
    if overlay.last_run_at is None:
        return True
    last = _aware(overlay.last_run_at)
    return (_aware(now) - last).total_seconds() >= interval


def _clock_due(overlay: EffectiveSchedule, local_now: datetime, tz: ZoneInfo) -> bool:
    if not overlay.clock_time:
        return False
    try:
        clock = parse_schedule_time(overlay.clock_time)
    except ValueError:
        logger.exception("invalid clock for job=%s value=%s", overlay.job_key, overlay.clock_time)
        return False
    if overlay.schedule_kind == "weekly_clock":
        if overlay.weekday is None or local_now.weekday() != overlay.weekday:
            return False
    if local_now.time().replace(tzinfo=None) < clock:
        return False
    return not _already_ran_on_local_date(overlay, local_now.date(), tz)


def execute_scheduled_job(db: Session, settings: Settings, job_key: str) -> str:
    if job_key == TELEGRAM_JOB_KEY:
        from backend.src.app.services.telegram_notifications import (
            run_daily_telegram_notifications,
        )

        run_daily_telegram_notifications(
            db,
            settings=settings.model_copy(update={"telegram_notifications_enabled": True}),
        )
        return "completed"
    if job_key == WEEKLY_BETA_JOB_KEY:
        from backend.src.app.services.weekly_beta_report import (
            generate_and_store_weekly_beta_report,
        )

        generate_and_store_weekly_beta_report(
            db,
            settings=settings,
            send_telegram=settings.weekly_beta_report_telegram_enabled,
            generated_by="scheduler",
        )
        return "completed"
    if job_key == CLOSING_ODDS_JOB_KEY:
        from backend.src.app.services.prematch_odds_snapshots import (
            run_closing_odds_capture_once,
        )

        run_closing_odds_capture_once(
            db, window_minutes=settings.closing_odds_capture_window_minutes
        )
        return "completed"
    if job_key == OPS_CHECKS_JOB_KEY:
        from backend.src.app.observability.notify import run_and_alert_ops_checks

        run_and_alert_ops_checks(db, settings)
        return "completed"
    if job_key == DB_BACKUP_JOB_KEY:
        from backend.src.service.postgres_backup import (
            DEFAULT_BACKUP_DIR,
            DEFAULT_RETENTION_DAYS,
            BackupError,
            perform_backup,
            resolve_db_target,
        )

        raw_retention = os.getenv("BACKUP_RETENTION_DAYS", "").strip()
        retention_days = (
            int(raw_retention) if raw_retention else DEFAULT_RETENTION_DAYS
        )
        encrypt = os.getenv("BACKUP_ENCRYPT", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        backup_dir = Path(os.getenv("BACKUP_DIR", DEFAULT_BACKUP_DIR))
        if not backup_dir.is_absolute():
            backup_dir = Path.cwd() / backup_dir
        try:
            target = resolve_db_target(database_url=settings.database_url)
            result = perform_backup(
                target=target,
                backup_dir=backup_dir,
                retention_days=retention_days,
                encrypt=encrypt,
                gpg_recipient=os.getenv("BACKUP_GPG_RECIPIENT") or None,
                gpg_passphrase_file=os.getenv("BACKUP_GPG_PASSPHRASE_FILE") or None,
            )
        except BackupError as exc:
            raise RuntimeError(str(exc)) from exc
        if not result.ok:
            raise RuntimeError(result.message)
        return "completed_with_errors" if result.warnings else "completed"
    raise ScheduledJobSettingsError(f"Job non eseguibile dallo scheduler: {job_key}")


def run_auxiliary_jobs(now: datetime | None = None) -> list[tuple[str, str]]:
    """Run due auxiliary jobs owned by the report-scheduler worker."""

    settings = get_settings()
    tz = ZoneInfo(settings.scheduled_reports_timezone)
    local_now = now.astimezone(tz) if now is not None else datetime.now(tz)
    utc_now = local_now.astimezone(timezone.utc)
    results: list[tuple[str, str]] = []

    from backend.src.app.db.session import SessionLocal

    for job_key in AUXILIARY_JOB_KEYS:
        try:
            with SessionLocal() as db:
                overlay = get_effective_schedule(db, settings, job_key)
                if not overlay.enabled:
                    continue
                if _is_currently_running(overlay, utc_now):
                    continue
                definition = get_job_definition(job_key)
                due = False
                if definition.schedule_kind == "interval":
                    due = _interval_due(overlay, utc_now)
                else:
                    due = _clock_due(overlay, local_now, tz)
                if not due:
                    continue
                mark_job_run(db, settings, job_key, "running", when=utc_now)
                try:
                    status = execute_scheduled_job(db, settings, job_key)
                except Exception:
                    logger.exception("scheduled auxiliary job failed job=%s", job_key)
                    mark_job_run(db, settings, job_key, "failed", when=utc_now)
                    results.append((job_key, "failed"))
                    continue
                mark_job_run(db, settings, job_key, status, when=utc_now)
                results.append((job_key, status))
        except SQLAlchemyError:
            logger.exception("scheduled auxiliary job db error job=%s", job_key)
        except ScheduledJobSettingsError:
            logger.exception("scheduled auxiliary job config error job=%s", job_key)
    return results
