"""CLI: dedicated pre-kickoff closing-odds capture.

The daily import (``run_global_update`` / ``daily_pipeline``) only seals a
``closing`` odds snapshot opportunistically, when the batch happens to run
while a match is already live (see ``seal_closing_from_last_prematch``). That
produces very low and irregular CLV coverage (see
docs/SCHEDULING.md#closing-odds-pre-kickoff-job).

This job is meant to run frequently (every 1-5 minutes, e.g. via cron/Task
Scheduler) and does a single pass each time: find ``next_fixture`` rows whose
scheduled kickoff falls within the next ``--window-minutes`` and fetch+append
a fresh ``closing`` odds snapshot for each. Running it repeatedly as kickoff
approaches naturally produces several ``closing`` rows per fixture; consumers
(``published_live_stats._resolve_clv``) already pick the one with the latest
``captured_at`` per bookmaker, so no downstream change is required.

Disabled by default (``CLOSING_ODDS_JOB_ENABLED=false``): enable only once a
frequent external cron/scheduler is actually configured, otherwise a single
daily/occasional invocation would only capture whichever fixtures happen to be
inside the window at that moment (better than nothing, but not the intended
"dense" pre-kickoff coverage). See
docs/SCHEDULING.md#closing-odds-job-dedicato-pre-kickoff.

Examples:
  python -m backend.src.jobs.run_closing_odds_capture --dry-run
  python -m backend.src.jobs.run_closing_odds_capture
  python -m backend.src.jobs.run_closing_odds_capture --window-minutes 45 --json
  python -m backend.src.jobs.run_closing_odds_capture --force  # ignore CLOSING_ODDS_JOB_ENABLED
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from backend.src.app.core.config import get_settings
from backend.src.app.core.env_files import load_backend_env_files
from backend.src.app.db.session import SessionLocal
from backend.src.app.observability.context import ensure_correlation_id
from backend.src.app.observability.setup import setup_observability
from backend.src.app.services.prematch_odds_snapshots import (
    find_fixtures_pending_closing_capture,
    run_closing_odds_capture_once,
)

load_backend_env_files(override=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture dedicated pre-kickoff closing odds snapshots"
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=None,
        help="Minutes before kickoff a fixture enters the capture window "
        "(default: CLOSING_ODDS_CAPTURE_WINDOW_MINUTES)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list fixtures currently inside the window; no API calls/writes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if CLOSING_ODDS_JOB_ENABLED=false",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_observability(settings)
    ensure_correlation_id(f"closing-odds-capture-{os.getpid()}")
    logger = logging.getLogger(__name__)

    window_minutes = args.window_minutes or settings.closing_odds_capture_window_minutes

    if not settings.closing_odds_job_enabled and not args.force:
        message = (
            "closing odds capture skipped: CLOSING_ODDS_JOB_ENABLED=false "
            "(use --force to run once anyway)"
        )
        if args.json:
            print(json.dumps({"skipped": True, "reason": "job_disabled"}, indent=2))
        else:
            logger.info(message)
        return 0

    with SessionLocal() as db:
        if args.dry_run:
            pending = find_fixtures_pending_closing_capture(db, window_minutes=window_minutes)
            payload = {
                "dry_run": True,
                "window_minutes": window_minutes,
                "candidates": len(pending),
                "event_keys": [event_key for event_key, _kickoff in pending],
            }
            if args.json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                logger.info(
                    "closing_odds_capture dry_run window_minutes=%s candidates=%s event_keys=%s",
                    window_minutes,
                    payload["candidates"],
                    payload["event_keys"],
                )
            return 0

        summary = run_closing_odds_capture_once(db, window_minutes=window_minutes)

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        logger.info(
            "closing_odds_capture window_minutes=%s candidates=%s captured=%s "
            "inserted_rows=%s skipped_no_odds=%s failed=%s",
            summary["window_minutes"],
            summary["candidates"],
            summary["captured"],
            summary["inserted_rows"],
            summary["skipped_no_odds"],
            summary["failed"],
        )

    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())


