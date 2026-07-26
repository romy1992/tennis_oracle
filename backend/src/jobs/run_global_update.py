"""
Production daily job: runs the same global-update orchestrator as the UI button.

Features:
  - distributed DB lock (no concurrent runs)
  - idempotent same-day skip (unless --force)
  - configurable retry / per-step timeout via env
  - crash recovery via --resume
  - optional cloud sync
  - process exit codes for cron/workers

Examples:
  python -m backend.src.jobs.run_global_update
  python -m backend.src.jobs.run_global_update --force --sync-cloud
  python -m backend.src.jobs.run_global_update --resume
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from backend.src.app.core.config import get_settings
from backend.src.app.db.session import SessionLocal
from backend.src.app.observability.context import ensure_correlation_id
from backend.src.app.observability.setup import setup_observability
from backend.src.app.services.global_update import (
    exit_code_for_run,
    get_resumable_run,
    reconcile_orphaned_runs,
    start_global_update,
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../properties/config.env")
load_dotenv(dotenv_path=CONFIG_PATH)

setup_observability(get_settings())
ensure_correlation_id(f"job-global-update-{os.getpid()}")
logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def run_job(
    *,
    force: bool = False,
    resume: bool = False,
    resume_run_id: int | None = None,
    sync_cloud: bool | None = None,
    days_forward: int = 10,
    days_back_fixtures: int = 3,
    auto_resume: bool = True,
) -> int:
    """Execute the shared orchestrator in blocking mode. Returns process exit code."""
    if sync_cloud is None:
        sync_cloud = _env_flag("SYNC_CLOUD", default=False)

    with SessionLocal() as db:
        reconciled = reconcile_orphaned_runs(db)
        if reconciled:
            logger.warning("Marked %s orphaned run(s) as interrupted", reconciled)

        effective_resume = resume
        effective_resume_id = resume_run_id
        if not force and not resume and resume_run_id is None and auto_resume:
            resumable = get_resumable_run(db)
            if resumable is not None:
                logger.info(
                    "Auto-resuming interrupted/failed run_id=%s status=%s",
                    resumable.id,
                    resumable.status,
                )
                effective_resume = True
                effective_resume_id = resumable.id

        run, message = start_global_update(
            db,
            origin="job",
            force=force,
            days_forward=days_forward,
            days_back_fixtures=days_back_fixtures,
            sync_cloud=sync_cloud,
            resume=effective_resume,
            resume_run_id=effective_resume_id,
            blocking=True,
        )
        code = exit_code_for_run(run, message=message)
        if run is None:
            logger.warning("Job not started: %s (exit=%s)", message, code)
            return code

        logger.info(
            "Job finished run_id=%s status=%s duration=%ss exit=%s — %s",
            run.id,
            run.status,
            run.duration_seconds,
            code,
            message,
        )
        if run.errors_json:
            logger.info("Errors: %s", run.errors_json)
        return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Production global-update job (same orchestrator as UI)."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if a completed run already exists for today.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the latest interrupted/failed/cancelled run.",
    )
    parser.add_argument(
        "--resume-run-id",
        type=int,
        default=None,
        help="Resume a specific run id.",
    )
    parser.add_argument(
        "--no-auto-resume",
        action="store_true",
        help="Do not auto-resume interrupted runs (start a fresh run instead).",
    )
    parser.add_argument(
        "--sync-cloud",
        action="store_true",
        help="Enable cloud sync step (or set SYNC_CLOUD=true).",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Disable cloud sync even if SYNC_CLOUD=true.",
    )
    parser.add_argument(
        "--days-forward",
        type=int,
        default=10,
        help="Days of upcoming fixtures to import/predict.",
    )
    parser.add_argument(
        "--days-back-fixtures",
        type=int,
        default=3,
        help="Days back for played-fixture import.",
    )
    args = parser.parse_args(argv)

    sync_cloud: bool | None
    if args.no_sync:
        sync_cloud = False
    elif args.sync_cloud:
        sync_cloud = True
    else:
        sync_cloud = None

    return run_job(
        force=args.force,
        resume=args.resume or args.resume_run_id is not None,
        resume_run_id=args.resume_run_id,
        sync_cloud=sync_cloud,
        days_forward=args.days_forward,
        days_back_fixtures=args.days_back_fixtures,
        auto_resume=not args.no_auto_resume,
    )


if __name__ == "__main__":
    sys.exit(main())
