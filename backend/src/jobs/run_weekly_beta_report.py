"""CLI: generate weekly beta report, persist, notify admin on Telegram.

Examples:
  python -m backend.src.jobs.run_weekly_beta_report --dry-run
  python -m backend.src.jobs.run_weekly_beta_report
  python -m backend.src.jobs.run_weekly_beta_report --week-start 2026-07-13 --force
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date

from dotenv import load_dotenv

from backend.src.app.core.config import get_settings
from backend.src.app.db.session import SessionLocal
from backend.src.app.observability.context import ensure_correlation_id
from backend.src.app.observability.setup import setup_observability
from backend.src.app.services.weekly_beta_report import (
    compute_weekly_beta_report_payload,
    generate_and_store_weekly_beta_report,
    iso_week_bounds,
    previous_completed_iso_week,
    report_to_read,
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../properties/config.env")
load_dotenv(dotenv_path=CONFIG_PATH)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate tennis_oracle weekly beta report (persist + admin Telegram)"
    )
    parser.add_argument(
        "--week-start",
        default=None,
        help="Monday YYYY-MM-DD of the ISO week to report (default: previous completed week)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute and overwrite an existing report for the same week",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Skip admin Telegram summary",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute payload and print JSON without persisting or sending Telegram",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON to stdout",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_observability(settings)
    ensure_correlation_id(f"weekly-beta-report-{os.getpid()}")
    logger = logging.getLogger(__name__)

    week_start: date | None = None
    if args.week_start:
        week_start = date.fromisoformat(args.week_start)
        bounds_start, _ = iso_week_bounds(week_start)
        if week_start != bounds_start:
            raise SystemExit(
                f"--week-start must be a Monday (ISO); got {week_start}, expected {bounds_start}"
            )
    else:
        week_start, _ = previous_completed_iso_week()

    with SessionLocal() as db:
        if args.dry_run:
            payload = compute_weekly_beta_report_payload(db, week_start=week_start)
            data = payload.model_dump(mode="json")
            if args.json:
                print(json.dumps(data, indent=2, default=str))
            else:
                logger.info(
                    "weekly_beta_report dry_run week=%s users_total=%s active=%s tips=%s roi=%s",
                    payload.current.week_label,
                    payload.current.users.total_users,
                    payload.current.users.active_users,
                    payload.current.live_tips.predictions_published,
                    payload.current.live_tips.roi_pct,
                )
                print(json.dumps(data, indent=2, default=str))
            return 0

        row, created, telegram = generate_and_store_weekly_beta_report(
            db,
            week_start=week_start,
            settings=settings,
            send_telegram=not args.no_telegram,
            force=args.force,
            generated_by="job",
        )
        read = report_to_read(row)
        out = {
            "created": created,
            "telegram": telegram,
            "report": read.model_dump(mode="json"),
        }
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            logger.info(
                "weekly_beta_report id=%s week=%s created=%s telegram_status=%s",
                row.id,
                row.week_label,
                created,
                row.telegram_status,
            )

    if telegram.get("sent") or telegram.get("skipped") or args.no_telegram:
        return 0
    # Delivery attempted but failed channels.
    if telegram.get("telegram") in ("ok", "disabled") and telegram.get("skipped"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
