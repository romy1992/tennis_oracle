"""In-app scheduler for nightly global update."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.src.app.core.config import get_settings
from backend.src.app.db.session import SessionLocal
from backend.src.app.services.global_update import start_global_update

logger = logging.getLogger(__name__)

_scheduler_thread: threading.Thread | None = None
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


def start_global_update_scheduler() -> None:
    global _scheduler_thread
    settings = get_settings()
    if not settings.global_update_cron_enabled:
        return
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        name="global-update-cron",
        daemon=True,
    )
    _scheduler_thread.start()


def stop_global_update_scheduler() -> None:
    _stop_event.set()
