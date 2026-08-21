"""CLI: send the final daily betting-slip recap through Telegram."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.src.app.core.config import get_settings
from backend.src.app.core.env_files import load_backend_env_files
from backend.src.app.db.session import SessionLocal
from backend.src.app.observability.context import ensure_correlation_id
from backend.src.app.observability.setup import setup_observability
from backend.src.app.services.betting_slip_live_scores import (
    run_betting_slip_live_poll_once,
)
from backend.src.app.services.telegram_notifications import (
    KIND_SLIP_RECAP,
    run_notification_kind,
)

load_backend_env_files(override=False)


def _parse_clock(value: str) -> time:
    parsed = time.fromisoformat(value.strip())
    return parsed.replace(second=0, microsecond=0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send final betting-slip Telegram recap")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_observability(settings)
    ensure_correlation_id(f"betting-slip-recap-{os.getpid()}")
    logger = logging.getLogger(__name__)
    timezone = ZoneInfo(settings.betting_slip_timezone)
    local_now = datetime.now(timezone)
    recap_time = _parse_clock(settings.betting_slip_recap_time)
    target_date = (
        date.fromisoformat(args.date)
        if args.date
        else (
            local_now.date()
            if local_now.time() >= recap_time
            else local_now.date() - timedelta(days=1)
        )
    )

    if not settings.betting_slip_recap_enabled and not args.force:
        payload = {"skipped": True, "reason": "job_disabled"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            logger.info("betting slip recap skipped: job disabled")
        return 0
    if (
        target_date == local_now.date()
        and local_now.time() < recap_time
        and not args.force
    ):
        payload = {"skipped": True, "reason": "before_recap_time"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            logger.info("betting slip recap skipped: before configured time")
        return 0

    effective_settings = (
        settings.model_copy(update={"betting_slip_recap_enabled": True})
        if args.force and not settings.betting_slip_recap_enabled
        else settings
    )

    with SessionLocal() as db:
        try:
            live_summary = run_betting_slip_live_poll_once(
                db,
                target_date=target_date,
                settings=effective_settings,
            )
        except Exception as exc:
            logger.warning("Final live-score refresh failed: %s", exc)
            live_summary = {"error": str(exc)}
        recap = run_notification_kind(
            db,
            kind=KIND_SLIP_RECAP,
            content_date=target_date,
            settings=effective_settings,
            dry_run=args.dry_run,
            force=args.force,
        )

    payload = {"live_poll": live_summary, "recap": recap.to_dict()}
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        logger.info("betting_slip_recap %s", payload)
    return 1 if recap.failed else 0


if __name__ == "__main__":
    sys.exit(main())
