"""In-app scheduler for nightly global update."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from backend.src.app.core.config import get_settings
from backend.src.app.db.session import SessionLocal
from backend.src.app.services.global_update import start_global_update
from backend.src.app.services.betting_slip_live_scores import (
    run_betting_slip_live_poll_once,
)
from backend.src.app.services.scheduled_job_settings import (
    LIVE_POLL_JOB_KEY,
    RECAP_JOB_KEY,
    get_effective_schedule,
    mark_job_run,
)
from backend.src.app.services.telegram_notifications import (
    KIND_SLIP_RECAP,
    run_notification_kind,
)

logger = logging.getLogger(__name__)

_scheduler_thread: threading.Thread | None = None
_live_poll_thread: threading.Thread | None = None
_recap_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _parse_cron_time(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid cron time: {value}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid cron time: {value}")
    return hour, minute


def _should_run_now(now: datetime, target_hour: int, target_minute: int) -> bool:
    return now.hour == target_hour and now.minute == target_minute


def _scheduler_loop() -> None:
    settings = get_settings()
    if not settings.global_update_cron_enabled:
        logger.info("Global update cron disabled.")
        return

    try:
        target_hour, target_minute = _parse_cron_time(settings.global_update_cron_time)
        tz = ZoneInfo(settings.global_update_cron_timezone)
    except Exception as exc:
        logger.error("Invalid global update cron configuration: %s", exc)
        return

    last_run_date: date | None = None
    logger.info(
        "Global update cron started (%02d:%02d %s).",
        target_hour,
        target_minute,
        settings.global_update_cron_timezone,
    )

    while not _stop_event.is_set():
        now = datetime.now(tz)
        if _should_run_now(now, target_hour, target_minute) and last_run_date != now.date():
            logger.info("Triggering scheduled global update for %s.", now.date())
            with SessionLocal() as db:
                run, message = start_global_update(db, origin="cron", force=False)
                if run is None:
                    logger.warning("Scheduled global update skipped: %s", message)
                else:
                    logger.info("Scheduled global update started: run_id=%s", run.id)
                    last_run_date = now.date()
        _stop_event.wait(30)


def _live_poll_loop() -> None:
    logger.info("Betting-slip live poll scheduler started.")
    while not _stop_event.is_set():
        wait_seconds = 30
        try:
            settings = get_settings()
            with SessionLocal() as db:
                overlay = get_effective_schedule(db, settings, LIVE_POLL_JOB_KEY)
                wait_seconds = max(
                    30, int(overlay.interval_seconds or settings.betting_slip_live_poll_interval_seconds)
                )
                if overlay.enabled:
                    summary = run_betting_slip_live_poll_once(db, settings=settings)
                    mark_job_run(db, settings, LIVE_POLL_JOB_KEY, "completed")
                    logger.info("Betting-slip live poll completed: %s", summary)
        except Exception:
            logger.exception("Betting-slip live poll failed.")
        _stop_event.wait(wait_seconds)


def _recap_loop() -> None:
    logger.info("Betting-slip recap scheduler started.")
    last_run_date: date | None = None
    while not _stop_event.is_set():
        try:
            settings = get_settings()
            with SessionLocal() as db:
                overlay = get_effective_schedule(db, settings, RECAP_JOB_KEY)
            if overlay.enabled and overlay.clock_time:
                try:
                    target_hour, target_minute = _parse_cron_time(overlay.clock_time)
                    tz = ZoneInfo(settings.betting_slip_timezone)
                except Exception as exc:
                    logger.error("Invalid betting-slip recap configuration: %s", exc)
                else:
                    now = datetime.now(tz)
                    if (now.hour, now.minute) >= (target_hour, target_minute) and last_run_date != now.date():
                        runtime_settings = settings.model_copy(
                            update={"betting_slip_recap_enabled": True}
                        )
                        target_dates = [now.date() - timedelta(days=1), now.date()]
                        for target_date in target_dates:
                            try:
                                with SessionLocal() as db:
                                    run_betting_slip_live_poll_once(
                                        db,
                                        target_date=target_date,
                                        settings=runtime_settings,
                                    )
                                    summary = run_notification_kind(
                                        db,
                                        kind=KIND_SLIP_RECAP,
                                        content_date=target_date,
                                        settings=runtime_settings,
                                    )
                                    logger.info("Betting-slip recap attempt: %s", summary.to_dict())
                            except Exception:
                                logger.exception(
                                    "Betting-slip recap attempt failed for %s.", target_date
                                )
                        last_run_date = now.date()
                        with SessionLocal() as db:
                            mark_job_run(db, runtime_settings, RECAP_JOB_KEY, "completed")
        except Exception:
            logger.exception("Betting-slip recap scheduler failed.")
        _stop_event.wait(60)


def start_global_update_scheduler() -> None:
    global _scheduler_thread, _live_poll_thread, _recap_thread
    settings = get_settings()
    _stop_event.clear()
    if settings.global_update_cron_enabled and not (
        _scheduler_thread is not None and _scheduler_thread.is_alive()
    ):
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop,
            name="global-update-cron",
            daemon=True,
        )
        _scheduler_thread.start()
    if _live_poll_thread is None or not _live_poll_thread.is_alive():
        _live_poll_thread = threading.Thread(
            target=_live_poll_loop,
            name="betting-slip-live-poll",
            daemon=True,
        )
        _live_poll_thread.start()
    if _recap_thread is None or not _recap_thread.is_alive():
        _recap_thread = threading.Thread(
            target=_recap_loop,
            name="betting-slip-recap",
            daemon=True,
        )
        _recap_thread.start()


def stop_global_update_scheduler() -> None:
    _stop_event.set()
