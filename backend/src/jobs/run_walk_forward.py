"""CLI: run temporal walk-forward validation for every active market.

Does not overwrite holdout baseline metrics or replace the public/live model.

Examples:
  python -m backend.src.jobs.run_walk_forward --dry-run
  python -m backend.src.jobs.run_walk_forward
  python -m backend.src.jobs.run_walk_forward --mode rolling --versions v4
  python -m backend.src.jobs.run_walk_forward --versions v2,v3  # archived match-winner backtest
  python -m backend.src.jobs.run_walk_forward --versions first_set_winner_v2  # single market
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
from backend.src.app.ml.training.walk_forward import (
    WalkForwardConfig,
    run_walk_forward_validation,
    walk_forward_result_to_dict,
    write_walk_forward_report,
)
from backend.src.app.observability.context import ensure_correlation_id
from backend.src.app.observability.setup import setup_observability
from backend.src.app.schemas.walk_forward import WalkForwardTriggerRequest
from backend.src.app.services.walk_forward import (
    run_to_read,
    start_walk_forward_run,
)

load_backend_env_files(override=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run tennis_oracle temporal walk-forward validation (no public model change)"
    )
    parser.add_argument("--mode", choices=["expanding", "rolling"], default=None)
    parser.add_argument("--initial-train-days", type=int, default=None)
    parser.add_argument("--test-days", type=int, default=None)
    parser.add_argument("--step-days", type=int, default=None)
    parser.add_argument("--min-train-rows", type=int, default=None)
    parser.add_argument("--min-test-rows", type=int, default=None)
    parser.add_argument("--embargo-days", type=int, default=None)
    parser.add_argument("--edge-threshold", type=float, default=None)
    parser.add_argument("--random-state", type=int, default=None)
    parser.add_argument(
        "--versions",
        default=None,
        help=(
            "Comma-separated versions/markets (default: every active market — "
            "match-winner v4 + first_set_winner_v2 + over_under_games_v1)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute walk-forward without persisting DB rows (writes adhoc JSON report)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_observability(settings)
    ensure_correlation_id(f"walk-forward-{os.getpid()}")
    logger = logging.getLogger(__name__)

    versions = None
    if args.versions:
        versions = [part.strip() for part in args.versions.split(",") if part.strip()]

    request = WalkForwardTriggerRequest(
        mode=args.mode or settings.walk_forward_mode,  # type: ignore[arg-type]
        initial_train_days=args.initial_train_days or settings.walk_forward_initial_train_days,
        test_days=args.test_days or settings.walk_forward_test_days,
        step_days=args.step_days or settings.walk_forward_step_days,
        min_train_rows=args.min_train_rows or settings.walk_forward_min_train_rows,
        min_test_rows=args.min_test_rows or settings.walk_forward_min_test_rows,
        embargo_days=(
            args.embargo_days
            if args.embargo_days is not None
            else settings.walk_forward_embargo_days
        ),
        edge_threshold=(
            args.edge_threshold
            if args.edge_threshold is not None
            else settings.walk_forward_edge_threshold
        ),
        random_state=args.random_state or settings.walk_forward_random_state,
        versions=versions,  # type: ignore[arg-type]
        blocking=True,
    )

    if args.dry_run:
        config = WalkForwardConfig(
            mode=request.mode,
            initial_train_days=request.initial_train_days,
            test_days=request.test_days,
            step_days=request.step_days,
            min_train_rows=request.min_train_rows,
            min_test_rows=request.min_test_rows,
            embargo_days=request.embargo_days,
            edge_threshold=request.edge_threshold,
            random_state=request.random_state,
        )
        with SessionLocal() as db:
            result = run_walk_forward_validation(
                config,
                versions=tuple(versions) if versions else None,
                db=db,
            )
        path = write_walk_forward_report(result)
        payload = walk_forward_result_to_dict(result)
        payload["report_path"] = str(path)
        if args.json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            logger.info(
                "walk_forward dry_run completed folds=%s skipped=%s errors=%s report=%s",
                result.summary.get("folds_completed"),
                result.summary.get("folds_skipped"),
                result.summary.get("folds_errors"),
                path,
            )
            print(json.dumps(payload["summary"], indent=2, default=str))
        return 0

    with SessionLocal() as db:
        run, started, message = start_walk_forward_run(
            db,
            request=request,
            settings=settings,
            origin="job",
            created_by="job",
            blocking=True,
        )
        read = run_to_read(run)
        out = {
            "started": started,
            "message": message,
            "run": read.model_dump(mode="json"),
        }
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            logger.info(
                "walk_forward run_id=%s status=%s started=%s message=%s",
                run.id,
                run.status,
                started,
                message,
            )

    if run.status in ("completed", "completed_with_errors"):
        return 0 if run.status == "completed" else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
