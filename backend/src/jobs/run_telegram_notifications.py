"""CLI: send configurable Telegram user notifications.

Examples:
  python -m backend.src.jobs.run_telegram_notifications --dry-run
  python -m backend.src.jobs.run_telegram_notifications --kinds predictions,empty_day
  python -m backend.src.jobs.run_telegram_notifications --kinds results --date 2026-07-26
"""

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
from backend.src.app.services.telegram_notifications import (
    ALL_KINDS,
    NotificationKind,
    run_daily_telegram_notifications,
)

load_backend_env_files(override=False)


def _parse_kinds(raw: str | None) -> list[NotificationKind]:
    if not raw or not raw.strip():
        return list(ALL_KINDS)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    unknown = [p for p in parts if p not in ALL_KINDS]
    if unknown:
        raise SystemExit(
            f"Kind non validi: {', '.join(unknown)}. "
            f"Ammessi: {', '.join(ALL_KINDS)}"
        )
    return parts  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Send tennis_oracle Telegram user notifications"
    )
    parser.add_argument(
        "--kinds",
        default=None,
        help="Comma-separated: predictions,results,empty_day (default: all)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Content date YYYY-MM-DD for predictions/empty_day (default: today Rome)",
    )
    parser.add_argument(
        "--results-date",
        default=None,
        help="Results digest date YYYY-MM-DD (default: yesterday Rome)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build messages and mark recipients without calling Telegram API",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Resend even if dedupe already recorded a successful delivery",
    )
    parser.add_argument(
        "--model-version",
        default=None,
        help="Override PUBLIC_MODEL_VERSION for content",
    )
    parser.add_argument(
        "--model-name",
        default=None,
        help="Override PUBLIC_MODEL_NAME for content",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON summaries to stdout",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_observability(settings)
    ensure_correlation_id(f"telegram-notify-{os.getpid()}")
    logger = logging.getLogger(__name__)

    kinds = _parse_kinds(args.kinds)
    content_date = date.fromisoformat(args.date) if args.date else None
    results_date = date.fromisoformat(args.results_date) if args.results_date else None

    with SessionLocal() as db:
        summaries = run_daily_telegram_notifications(
            db,
            kinds=kinds,
            content_date=content_date,
            results_date=results_date,
            settings=settings,
            dry_run=args.dry_run,
            force=args.force,
            model_version=args.model_version,
            model_name=args.model_name,
        )

    payload = [s.to_dict() for s in summaries]
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        for summary in summaries:
            logger.info(
                "telegram_notify kind=%s date=%s recipients=%s sent=%s failed=%s skipped=%s preview=%s",
                summary.kind,
                summary.content_date,
                summary.recipients,
                summary.sent,
                summary.failed,
                summary.skipped,
                summary.message_preview,
            )

    if any(s.failed for s in summaries):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
