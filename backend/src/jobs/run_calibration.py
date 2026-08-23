"""CLI: run probability calibration analysis from walk-forward OOS data.

Does not activate calibration on the public/live model.

Examples:
  python -m backend.src.jobs.run_calibration --dry-run
  python -m backend.src.jobs.run_calibration
  python -m backend.src.jobs.run_calibration --versions v2,v3 --blocking
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
from backend.src.app.ml.training.calibration import (
    CalibrationConfig,
    calibration_result_to_dict,
    run_calibration_validation,
    write_calibration_report,
)
from backend.src.app.ml.training.walk_forward import WalkForwardConfig
from backend.src.app.observability.context import ensure_correlation_id
from backend.src.app.observability.setup import setup_observability
from backend.src.app.schemas.calibration import CalibrationTriggerRequest
from backend.src.app.services.calibration import run_to_read, start_calibration_run

load_backend_env_files(override=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run tennis_oracle probability calibration (no public model change)"
    )
    parser.add_argument("--n-bins", type=int, default=None)
    parser.add_argument("--min-bin-samples", type=int, default=None)
    parser.add_argument("--min-calibrator-train-samples", type=int, default=None)
    parser.add_argument("--mode", choices=["expanding", "rolling"], default=None)
    parser.add_argument("--initial-train-days", type=int, default=None)
    parser.add_argument("--test-days", type=int, default=None)
    parser.add_argument("--step-days", type=int, default=None)
    parser.add_argument("--min-train-rows", type=int, default=None)
    parser.add_argument("--min-test-rows", type=int, default=None)
    parser.add_argument("--embargo-days", type=int, default=None)
    parser.add_argument("--edge-threshold", type=float, default=None)
    parser.add_argument("--random-state", type=int, default=None)
    parser.add_argument("--versions", default=None, help="Comma-separated versions (default: all)")
    parser.add_argument(
        "--methods",
        default=None,
        help="Comma-separated methods: raw,platt,isotonic",
    )
    parser.add_argument("--walk-forward-run-id", type=int, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute calibration without persisting DB rows (writes adhoc JSON report)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_observability(settings)
    ensure_correlation_id(f"calibration-{os.getpid()}")
    logger = logging.getLogger(__name__)

    versions = None
    if args.versions:
        versions = [part.strip() for part in args.versions.split(",") if part.strip()]
    methods = None
    if args.methods:
        methods = [part.strip() for part in args.methods.split(",") if part.strip()]

    request = CalibrationTriggerRequest(
        n_bins=args.n_bins or settings.calibration_n_bins,
        min_bin_samples=args.min_bin_samples or settings.calibration_min_bin_samples,
        min_calibrator_train_samples=(
            args.min_calibrator_train_samples or settings.calibration_min_calibrator_train_samples
        ),
        methods=methods,  # type: ignore[arg-type]
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
        walk_forward_run_id=args.walk_forward_run_id,
        blocking=True,
    )

    if args.dry_run:
        wf = WalkForwardConfig(
            mode=request.mode or settings.walk_forward_mode,  # type: ignore[arg-type]
            initial_train_days=request.initial_train_days or settings.walk_forward_initial_train_days,
            test_days=request.test_days or settings.walk_forward_test_days,
            step_days=request.step_days or settings.walk_forward_step_days,
            min_train_rows=request.min_train_rows or settings.walk_forward_min_train_rows,
            min_test_rows=request.min_test_rows or settings.walk_forward_min_test_rows,
            embargo_days=(
                request.embargo_days
                if request.embargo_days is not None
                else settings.walk_forward_embargo_days
            ),
            edge_threshold=(
                request.edge_threshold
                if request.edge_threshold is not None
                else settings.walk_forward_edge_threshold
            ),
            random_state=request.random_state or settings.walk_forward_random_state,
        )
        config = CalibrationConfig(
            n_bins=request.n_bins or settings.calibration_n_bins,
            min_bin_samples=request.min_bin_samples or settings.calibration_min_bin_samples,
            min_calibrator_train_samples=(
                request.min_calibrator_train_samples
                or settings.calibration_min_calibrator_train_samples
            ),
            methods=tuple(methods) if methods else ("raw", "platt", "isotonic"),  # type: ignore[arg-type]
            walk_forward=wf,
        )
        with SessionLocal() as db:
            result = run_calibration_validation(
                config,
                versions=tuple(versions) if versions else None,
                db=db,
                walk_forward_run_id=request.walk_forward_run_id,
                persist_artifacts=False,
            )
        path = write_calibration_report(result)
        payload = calibration_result_to_dict(result)
        payload["report_path"] = str(path)
        if args.json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            logger.info(
                "calibration dry_run completed models=%s oos=%s report=%s",
                result.summary.get("models_with_oos"),
                result.summary.get("oos_samples_total"),
                path,
            )
            print(json.dumps(result.summary, indent=2, default=str))
        return 0

    with SessionLocal() as db:
        run, started, message = start_calibration_run(
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
                "calibration run_id=%s status=%s started=%s message=%s",
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
