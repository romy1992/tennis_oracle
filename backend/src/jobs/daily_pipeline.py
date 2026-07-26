"""
Compatibility wrapper for the daily job.

Historically this module ran a lighter single-model pipeline plus optional cloud
sync. Production now uses the shared global-update orchestrator (same as the UI
"Aggiorna tutto" button) via ``backend.src.jobs.run_global_update``.

This module remains importable for existing cron/scripts and delegates to that
orchestrator. Prefer:

  python -m backend.src.jobs.run_global_update

See docs/SCHEDULING.md.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Iterable, Optional

from dotenv import load_dotenv

from backend.src.app.ml.model_versioning import ModelVersion
from backend.src.jobs.run_global_update import run_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../properties/config.env")
load_dotenv(dotenv_path=CONFIG_PATH)

DEFAULT_SYNC_TABLES = ("fixture", "next_fixture", "match_prediction")


class DailyPipeline:
    """Backward-compatible facade that delegates to the shared orchestrator."""

    def __init__(
        self,
        sync_cloud: bool = True,
        sync_tables: Optional[Iterable[str]] = None,
        days_back_start: int = 1,
        days_back_stop: int = 0,
        days_forward: int = 10,
        days_back_next: int = 3,
        prediction_model_version: ModelVersion = "v2",
        prediction_model_name: str | None = None,
    ):
        self.sync_cloud = sync_cloud
        self.sync_tables = list(sync_tables or DEFAULT_SYNC_TABLES)
        self.days_back_start = days_back_start
        self.days_back_stop = days_back_stop
        self.days_forward = days_forward
        self.days_back_next = days_back_next
        self.prediction_model_version = prediction_model_version
        self.prediction_model_name = prediction_model_name
        if prediction_model_name or prediction_model_version:
            logger.warning(
                "DailyPipeline now runs the full global-update orchestrator "
                "(all enabled model combinations). "
                "prediction_model_version=%s prediction_model_name=%s are ignored. "
                "sync_tables=%s is ignored (fixed set: fixture, next_fixture, match_prediction).",
                prediction_model_version,
                prediction_model_name,
                self.sync_tables,
            )

    def run(self) -> dict:
        code = run_job(
            force=True,
            sync_cloud=self.sync_cloud,
            days_forward=self.days_forward,
            days_back_fixtures=max(self.days_back_next, self.days_back_start, 1),
            auto_resume=True,
        )
        return {
            "orchestrator": "global_update",
            "exit_code": code,
            "sync_cloud": self.sync_cloud,
            "days_forward": self.days_forward,
        }


def run_daily_pipeline(
    sync_cloud: Optional[bool] = None,
    sync_tables: Optional[Iterable[str]] = None,
    days_forward: int = 10,
    prediction_model_version: ModelVersion = "v2",
    prediction_model_name: str | None = None,
) -> dict:
    if sync_cloud is None:
        sync_cloud = os.getenv("SYNC_CLOUD", "true").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    pipeline = DailyPipeline(
        sync_cloud=sync_cloud,
        sync_tables=sync_tables,
        days_forward=days_forward,
        prediction_model_version=prediction_model_version,
        prediction_model_name=prediction_model_name,
    )
    return pipeline.run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Legacy entrypoint: delegates to run_global_update "
            "(same orchestrator as the UI)."
        )
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Esegue senza sync verso cloud.",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        default=None,
        help="Ignored (kept for CLI compatibility).",
    )
    parser.add_argument(
        "--prediction-model-version",
        choices=["v1", "v2", "v3"],
        default="v2",
        help="Ignored: global update runs all enabled combinations.",
    )
    parser.add_argument(
        "--prediction-model-name",
        default=None,
        help="Ignored: global update runs all enabled combinations.",
    )
    parser.add_argument(
        "--days-forward",
        type=int,
        default=10,
        help="Numero di giorni futuri da importare e predire.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Forza una nuova run anche se già completata oggi.",
    )
    args = parser.parse_args()
    # Prefer process exit codes for cron; force=True preserves legacy always-run behaviour.
    from backend.src.jobs.run_global_update import run_job as _run_job

    code = _run_job(
        force=True if args.force else True,
        sync_cloud=not args.no_sync,
        days_forward=args.days_forward,
        auto_resume=True,
    )
    sys.exit(code)
