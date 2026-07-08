"""
Pipeline giornaliera:
  1) import fixtures storici/recenti nel DB locale
  2) import prossimi match in next_fixture + promozione completati
  3) genera e salva previsioni per i prossimi 10 giorni
  4) sync verso DB cloud (DATABASE_TARGET_URL) con upsert

Esecuzione manuale:
  python -m backend.src.jobs.daily_pipeline

Cron locale consigliato alle 09:00 (vedi docs/SCHEDULING.md).
"""
import logging
import os
from typing import Iterable, Optional

from dotenv import load_dotenv

from backend.src.service.database_migrator import run_migration
from backend.src.service.import_fixtures import run_daily_fixture_import
from backend.src.service.import_next_fixtures import run_daily_next_fixture_import
from backend.src.jobs.generate_upcoming_predictions import run_upcoming_prediction_generation
from backend.src.app.ml.model_versioning import ModelVersion

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "../../properties/config.env"
)
load_dotenv(dotenv_path=CONFIG_PATH)

DEFAULT_SYNC_TABLES = ("fixture", "next_fixture", "match_prediction")


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

    def run(self) -> dict:
        logger.info("=== DailyPipeline Step A: import fixtures (locale) ===")
        run_daily_fixture_import(
            days_back_start=self.days_back_start,
            days_back_stop=self.days_back_stop,
        )

        logger.info("=== DailyPipeline Step B: import next fixtures (locale) ===")
        next_summary = run_daily_next_fixture_import(
            days_forward=self.days_forward,
            days_back=self.days_back_next,
        )

        logger.info("=== DailyPipeline Step C: generate upcoming predictions ===")
        prediction_summary = run_upcoming_prediction_generation(
            days_forward=self.days_forward,
            model_version=self.prediction_model_version,
            model_name=self.prediction_model_name,
        )

        result = {
            "import": "ok",
            "next_fixtures": next_summary,
            "predictions": prediction_summary,
            "sync": None,
        }
        if not self.sync_cloud:
            logger.info("Sync cloud disabilitata (SYNC_CLOUD=false).")
            return result

        source = os.getenv("DATABASE_SOURCE_URL") or os.getenv("DATABASE_URL")
        target = os.getenv("DATABASE_TARGET_URL")
        if not source or not target:
            logger.warning(
                "Sync cloud saltata: servono DATABASE_SOURCE_URL (o DATABASE_URL) "
                "e DATABASE_TARGET_URL in properties/config.env"
            )
            return result
        if source == target:
            raise ValueError("SOURCE e TARGET non possono essere uguali.")

        logger.info("=== DailyPipeline Step D: sync verso cloud (upsert) ===")
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
    parser.add_argument(
        "--prediction-model-version",
        choices=["v1", "v2", "v3"],
        default="v2",
        help="Versione modello da usare per generare le previsioni.",
    )
    parser.add_argument(
        "--prediction-model-name",
        default=None,
        help="Nome modello da usare. Se omesso, viene scelto automaticamente dalle metriche.",
    )
    parser.add_argument(
        "--days-forward",
        type=int,
        default=10,
        help="Numero di giorni futuri da importare e predire.",
    )
    args = parser.parse_args()
    pipeline = DailyPipeline(
        sync_cloud=not args.no_sync,
        sync_tables=args.tables,
        days_forward=args.days_forward,
        prediction_model_version=args.prediction_model_version,
        prediction_model_name=args.prediction_model_name,
    )
    pipeline.run()
