"""CLI: run operational checks and optionally send admin alerts.

Examples:
  python -m backend.src.jobs.run_ops_checks
  python -m backend.src.jobs.run_ops_checks --alert
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
from backend.src.app.observability.notify import run_and_alert_ops_checks
from backend.src.app.observability.ops_checks import run_ops_checks
from backend.src.app.observability.setup import setup_observability

load_backend_env_files(override=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run tennis_oracle operational checks")
    parser.add_argument(
        "--alert",
        action="store_true",
        help="Send Telegram/webhook admin alerts when checks fail",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON report to stdout",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_observability(settings)
    ensure_correlation_id(f"ops-checks-{os.getpid()}")
    logger = logging.getLogger(__name__)

    with SessionLocal() as db:
        if args.alert:
            report = run_and_alert_ops_checks(db, settings)
        else:
            report = run_ops_checks(
                db,
                import_max_age_hours=settings.ops_import_max_age_hours,
                predictions_lookback_hours=settings.ops_predictions_lookback_hours,
                max_duration_seconds=settings.ops_pipeline_max_duration_seconds,
                public_model_version=settings.public_model_version,
                public_model_name=settings.public_model_name,
            )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        logger.info("ops_checks status=%s", report.get("status"))
        for check in report.get("checks") or []:
            logger.info(
                "check name=%s status=%s message=%s",
                check.get("name"),
                check.get("status"),
                check.get("message"),
            )

    status = report.get("status")
    if status == "critical":
        return 2
    if status == "warning":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
