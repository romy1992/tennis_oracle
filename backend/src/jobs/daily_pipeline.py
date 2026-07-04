"""
Pipeline giornaliera:
  1) import fixtures nel DB locale (DATABASE_URL / DATABASE_SOURCE_URL)
  2) sync verso DB cloud (DATABASE_TARGET_URL) con upsert

Esecuzione manuale:
  python3 -m src.jobs.daily_pipeline

Cron locale consigliato alle 09:00 (vedi docs/SCHEDULING.md).
"""
import logging
import os
from typing import Iterable, Optional

from dotenv import load_dotenv

from backend.src.service.database_migrator import run_migration
from backend.src.service.import_fixtures import run_daily_fixture_import

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "../../properties/config.env"
)
load_dotenv(dotenv_path=CONFIG_PATH)

DEFAULT_SYNC_TABLES = ("fixture",)


class DailyPipeline:
    """
    Job giornaliero: import API -> DB locale -> sync DB cloud.
    """

    def __init__(
        self,
        sync_cloud: bool = True,
        sync_tables: Optional[Iterable[str]] = None,
        days_back_start: int = 1,
        days_back_stop: int = 0,
    ):
        self.sync_cloud = sync_cloud
        self.sync_tables = list(sync_tables or DEFAULT_SYNC_TABLES)
        self.days_back_start = days_back_start
        self.days_back_stop = days_back_stop

    def run(self) -> dict:
        logger.info("=== DailyPipeline: import fixtures (locale) ===")
        run_daily_fixture_import(
            days_back_start=self.days_back_start,
            days_back_stop=self.days_back_stop,
        )

        result = {"import": "ok", "sync": None}
        if not self.sync_cloud:
            logger.info("Sync cloud disabilitata (SYNC_CLOUD=false).")
            return result

        source = os.getenv("DATABASE_SOURCE_URL") or os.getenv("DATABASE_URL")
        target = os.getenv("DATABASE_TARGET_URL")
        if not source or not target:
            raise ValueError(
                "Per sync cloud servono DATABASE_SOURCE_URL (o DATABASE_URL) "
                "e DATABASE_TARGET_URL in properties/config.env"
            )
        if source == target:
            raise ValueError("SOURCE e TARGET non possono essere uguali.")

        logger.info("=== DailyPipeline: sync verso cloud (upsert) ===")
        summary = run_migration(
            upsert=True,
            tables=self.sync_tables,
        )
        result["sync"] = summary
        logger.info("=== DailyPipeline completata ===")
        return result


def run_daily_pipeline(
    sync_cloud: Optional[bool] = None,
    sync_tables: Optional[Iterable[str]] = None,
) -> dict:
    if sync_cloud is None:
        sync_cloud = os.getenv("SYNC_CLOUD", "true").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    pipeline = DailyPipeline(sync_cloud=sync_cloud, sync_tables=sync_tables)
    return pipeline.run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Job giornaliero import + sync cloud.")
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Esegue solo import locale, senza sync verso cloud.",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        default=None,
        help="Tabelle da sincronizzare (default: fixture).",
    )
    args = parser.parse_args()
    run_daily_pipeline(sync_cloud=not args.no_sync, sync_tables=args.tables)
