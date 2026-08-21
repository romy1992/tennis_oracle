"""CLI: one pass of live-score polling for today's persisted betting slips."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date

from backend.src.app.core.config import get_settings
from backend.src.app.core.env_files import load_backend_env_files
from backend.src.app.db.session import SessionLocal
from backend.src.app.observability.context import ensure_correlation_id
from backend.src.app.observability.setup import setup_observability
from backend.src.app.services.betting_slip_live_scores import (
    pending_slip_event_keys,
    run_betting_slip_live_poll_once,
)

load_backend_env_files(override=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Poll live scores for betting-slip fixtures")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_observability(settings)
    ensure_correlation_id(f"betting-slip-live-poll-{os.getpid()}")
    logger = logging.getLogger(__name__)
    target_date = date.fromisoformat(args.date) if args.date else None

    if not settings.betting_slip_live_poll_enabled and not args.force:
        payload = {"skipped": True, "reason": "job_disabled"}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            logger.info("betting slip live poll skipped: job disabled")
        return 0

    with SessionLocal() as db:
        if args.dry_run:
            resolved_date = target_date or date.today()
            event_keys = sorted(pending_slip_event_keys(db, target_date=resolved_date))
            payload = {
                "dry_run": True,
                "date": resolved_date.isoformat(),
                "candidates": len(event_keys),
                "event_keys": event_keys,
            }
        else:
            payload = run_betting_slip_live_poll_once(
                db,
                target_date=target_date,
                settings=settings,
            )

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        logger.info("betting_slip_live_poll %s", payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
