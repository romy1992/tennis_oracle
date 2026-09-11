"""Persistent scheduler for daily and weekly operational report jobs.

The process is intended to run as one dedicated service in local/dev/prod.
Database schedule keys still prevent duplicates when multiple services point at
the same target database.

Examples:
  python -m backend.src.jobs.run_report_scheduler
  python -m backend.src.jobs.run_report_scheduler --run due
  python -m backend.src.jobs.run_report_scheduler --run daily --date 2026-08-31
  python -m backend.src.jobs.run_report_scheduler --run weekly --date 2026-08-31
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.src.app.core.config import get_settings
from backend.src.app.core.env_files import load_backend_env_files
from backend.src.app.db.session import SessionLocal
from backend.src.app.observability.context import ensure_correlation_id
from backend.src.app.observability.email_reports import validate_email_settings
from backend.src.app.observability.setup import setup_observability
from backend.src.app.services.scheduled_job_settings import (
    DAILY_JOB_KEY,
    WEEKLY_JOB_KEY,
    get_effective_schedule,
    mark_job_run,
    run_auxiliary_jobs,
)
from backend.src.app.services.scheduled_reports import (
    DAILY_JOB_NAME,
    WEEKLY_JOB_NAME,
    get_scheduled_job,
    list_stale_daily_report_dates,
    parse_schedule_time,
    resolve_job_source,
    run_daily_scheduled_report,
    run_weekly_scheduled_report,
)

load_backend_env_files(override=False)

logger = logging.getLogger(__name__)
_STOP = threading.Event()


def _parse_date(raw: str | None, timezone_name: str) -> date:
    if raw:
        return date.fromisoformat(raw)
    return datetime.now(ZoneInfo(timezone_name)).date()


def _status_exit_code(status: str) -> int:
    if status == "completed":
        return 0
    if status == "completed_with_errors":
        return 1
    if status == "skipped":
        return 2
    return 3


def run_daily(scheduled_date: date) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        row, claimed = run_daily_scheduled_report(
            db,
            settings,
            scheduled_date=scheduled_date,
        )
        logger.info(
            "scheduled_daily job_id=%s status=%s claimed=%s source=%s",
            row.id,
            row.status,
            claimed,
            row.source_name,
        )
        return _status_exit_code(row.status)


def run_weekly(scheduled_date: date) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        row, claimed = run_weekly_scheduled_report(
            db,
            settings,
            scheduled_date=scheduled_date,
        )
        logger.info(
            "scheduled_weekly job_id=%s status=%s claimed=%s source=%s",
            row.id,
            row.status,
            claimed,
            row.source_name,
        )
        return _status_exit_code(row.status)


def run_due(now: datetime | None = None) -> list[tuple[str, int]]:
    settings = get_settings()
    tz = ZoneInfo(settings.scheduled_reports_timezone)
    local_now = now.astimezone(tz) if now is not None else datetime.now(tz)
    source = resolve_job_source(settings)
    results: list[tuple[str, int]] = []
    attempted_daily_dates: set[date] = set()

    with SessionLocal() as db:
        daily_overlay = get_effective_schedule(db, settings, DAILY_JOB_KEY)
        weekly_overlay = get_effective_schedule(db, settings, WEEKLY_JOB_KEY)

    # A one-shot Railway cron only sees today's schedule by default.  Inspect
    # older stale rows too, so a report lost immediately before a deploy or
    # process kill can be completed on a later tick.  The service layer still
    # reclaims it only when the matching global update is terminal.
    if daily_overlay.enabled:
        with SessionLocal() as db:
            stale_daily_dates = list_stale_daily_report_dates(db, settings, now=local_now)
        for stale_date in stale_daily_dates:
            attempted_daily_dates.add(stale_date)
            with SessionLocal() as db:
                row, claimed = run_daily_scheduled_report(
                    db,
                    settings,
                    scheduled_date=stale_date,
                    source=source,
                )
                if claimed:
                    mark_job_run(db, settings, DAILY_JOB_KEY, row.status)
                    results.append((DAILY_JOB_NAME, _status_exit_code(row.status)))

        daily_clock = parse_schedule_time(
            daily_overlay.clock_time or settings.scheduled_global_update_time
        )
        if (
            local_now.time().replace(tzinfo=None) >= daily_clock
            and local_now.date() not in attempted_daily_dates
        ):
            with SessionLocal() as db:
                row, claimed = run_daily_scheduled_report(
                    db,
                    settings,
                    scheduled_date=local_now.date(),
                    source=source,
                )
                if claimed:
                    mark_job_run(db, settings, DAILY_JOB_KEY, row.status)
                    results.append((DAILY_JOB_NAME, _status_exit_code(row.status)))

    if weekly_overlay.enabled:
        weekday = (
            weekly_overlay.weekday
            if weekly_overlay.weekday is not None
            else settings.scheduled_weekly_validation_day
        )
        if not (0 <= weekday <= 6):
            raise ValueError("SCHEDULED_WEEKLY_VALIDATION_DAY deve essere compreso tra 0 e 6")
        weekly_clock = parse_schedule_time(
            weekly_overlay.clock_time or settings.scheduled_weekly_validation_time
        )
        if (
            local_now.weekday() == weekday
            and local_now.time().replace(tzinfo=None) >= weekly_clock
        ):
            with SessionLocal() as db:
                if get_scheduled_job(db, WEEKLY_JOB_NAME, local_now.date()) is None:
                    row, _ = run_weekly_scheduled_report(
                        db,
                        settings,
                        scheduled_date=local_now.date(),
                        source=source,
                    )
                    mark_job_run(db, settings, WEEKLY_JOB_KEY, row.status)
                    results.append((WEEKLY_JOB_NAME, _status_exit_code(row.status)))
    return results


def _handle_stop(_signum: int, _frame: object) -> None:
    _STOP.set()


def serve() -> int:
    settings = get_settings()
    source = resolve_job_source(settings)
    ZoneInfo(settings.scheduled_reports_timezone)

    with SessionLocal() as db:
        daily_overlay = get_effective_schedule(db, settings, DAILY_JOB_KEY)
        weekly_overlay = get_effective_schedule(db, settings, WEEKLY_JOB_KEY)

    if daily_overlay.enabled or weekly_overlay.enabled:
        missing_email = validate_email_settings(settings)
        if missing_email:
            logger.error(
                "scheduled_reports email configuration incomplete: %s",
                ", ".join(missing_email),
            )
            return 5

    logger.info(
        "scheduled_jobs started daily_enabled=%s daily=%s weekly_enabled=%s "
        "weekly_day=%s weekly_time=%s timezone=%s source=%s url=%s host=%s path=%s",
        daily_overlay.enabled,
        daily_overlay.clock_time,
        weekly_overlay.enabled,
        weekly_overlay.weekday,
        weekly_overlay.clock_time,
        settings.scheduled_reports_timezone,
        source.name,
        source.url or "-",
        source.hostname,
        source.path,
    )

    poll_seconds = max(5, int(settings.scheduled_reports_poll_seconds))
    while not _STOP.is_set():
        try:
            for job_name, exit_code in run_due():
                logger.info("scheduled_reports completed job=%s exit=%s", job_name, exit_code)
            for job_name, status in run_auxiliary_jobs():
                logger.info("scheduled_auxiliary completed job=%s status=%s", job_name, status)
        except Exception:
            logger.exception("scheduled_reports polling iteration failed")
        _STOP.wait(poll_seconds)
    logger.info("scheduled_reports stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run tennis_oracle scheduled report jobs")
    parser.add_argument(
        "--run",
        choices=["serve", "due", "daily", "weekly"],
        default="serve",
        help="Persistent worker or one-shot execution mode",
    )
    parser.add_argument("--date", default=None, help="Schedule date in YYYY-MM-DD")
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_observability(settings)
    ensure_correlation_id(f"report-scheduler-{os.getpid()}")
    target_date = _parse_date(args.date, settings.scheduled_reports_timezone)

    if args.run == "daily":
        return run_daily(target_date)
    if args.run == "weekly":
        return run_weekly(target_date)
    if args.run == "due":
        results = run_due()
        aux = run_auxiliary_jobs()
        codes = [code for _, code in results]
        if any(status == "failed" for _, status in aux):
            codes.append(3)
        return max(codes, default=0)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    return serve()


if __name__ == "__main__":
    sys.exit(main())
