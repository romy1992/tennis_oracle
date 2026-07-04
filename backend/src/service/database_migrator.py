"""
Migrazione dati da un PostgreSQL sorgente (es. locale) a uno destinazione (es. cloud agent).

Configurazione (properties/config.env o variabili d'ambiente):
  DATABASE_SOURCE_URL  - DB di origine (es. il tuo PC)
  DATABASE_TARGET_URL  - DB di destinazione (es. server agent)

Esempio esecuzione dal tuo PC (sorgente = locale, destinazione = IP/tunnel cloud):
  export DATABASE_SOURCE_URL="postgresql://postgres:postgres@localhost:5432/tennis_db"
  export DATABASE_TARGET_URL="postgresql://postgres:postgres@<host-cloud>:5432/tennis_db"
  python3 -m src.service.database_migrator
"""
import logging
import os
from typing import Iterable, Optional

from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from backend.src.entity import (
    Event,
    Fixture,
    MatchPrediction,
    NextFixture,
    Player,
    Standing,
    Tournament,
)
from backend.src.entity.base import Base

_ = (Event, Tournament, Fixture, NextFixture, MatchPrediction, Standing, Player)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "../../properties/config.env"
)

DEFAULT_SOURCE_URL = "postgresql://postgres:postgres@localhost:5432/tennis_db"
DEFAULT_TARGET_URL = "postgresql://postgres:postgres@localhost:5432/tennis_db"

# Ordine rispettoso delle dipendenze logiche del dominio
TABLE_MIGRATION_ORDER = (
    "event",
    "tournament",
    "fixture",
    "next_fixture",
    "match_prediction",
    "standing",
    "player",
)

# Colonne univoche per upsert incrementale (sync giornaliero)
TABLE_CONFLICT_COLUMNS = {
    "event": ["event_type_key"],
    "tournament": ["tournament_key"],
    "fixture": ["event_key"],
    "next_fixture": ["event_key"],
    "match_prediction": ["event_key", "model_version"],
    "standing": ["player_key", "league"],
    "player": ["player_key"],
}


class DatabaseMigrator:
    """
    Copia tabelle e dati da un database PostgreSQL sorgente a uno destinazione.
    """

    def __init__(
        self,
        source_url: Optional[str] = None,
        target_url: Optional[str] = None,
        batch_size: int = 500,
        clear_target: bool = False,
        upsert: bool = False,
        tables: Optional[Iterable[str]] = None,
    ):
        load_dotenv(dotenv_path=CONFIG_PATH)
        self.source_url = source_url or os.getenv(
            "DATABASE_SOURCE_URL", DEFAULT_SOURCE_URL
        )
        self.target_url = target_url or os.getenv(
            "DATABASE_TARGET_URL", DEFAULT_TARGET_URL
        )
        self.batch_size = batch_size
        self.clear_target = clear_target
        self.upsert = upsert
        self.tables = list(tables) if tables else list(TABLE_MIGRATION_ORDER)

        self.source_engine = create_engine(self.source_url)
        self.target_engine = create_engine(self.target_url)

    def _mask_url(self, url: str) -> str:
        if "@" not in url:
            return url
        prefix, host_part = url.split("@", 1)
        if "://" in prefix:
            scheme, creds = prefix.split("://", 1)
            if ":" in creds:
                user, _ = creds.split(":", 1)
                return f"{scheme}://{user}:***@{host_part}"
        return f"***@{host_part}"

    def ensure_target_schema(self) -> None:
        """Verifica che lo schema di destinazione sia già gestito da Alembic."""
        expected_tables = set(Base.metadata.tables)
        existing_tables = set(inspect(self.target_engine).get_table_names())
        missing_tables = sorted(expected_tables - existing_tables)
        if missing_tables:
            raise RuntimeError(
                "Schema destinazione incompleto. Esegui prima "
                "`alembic upgrade head`. Tabelle mancanti: "
                + ", ".join(missing_tables)
            )
        logger.info("Schema destinazione verificato.")

    def _table_exists(self, engine: Engine, table_name: str) -> bool:
        return table_name in inspect(engine).get_table_names()

    def _resolve_tables(self) -> list[str]:
        missing_on_source = [
            t for t in self.tables if not self._table_exists(self.source_engine, t)
        ]
        if missing_on_source:
            raise ValueError(
                "Tabelle assenti sulla sorgente: "
                + ", ".join(missing_on_source)
            )
        return self.tables

    def clear_target_tables(self) -> None:
        """Svuota le tabelle di destinazione (TRUNCATE ... RESTART IDENTITY CASCADE)."""
        ordered_for_truncate = list(reversed(self.tables))
        tables_sql = ", ".join(ordered_for_truncate)
        stmt = text(
            f"TRUNCATE TABLE {tables_sql} RESTART IDENTITY CASCADE"
        )
        with self.target_engine.begin() as conn:
            conn.execute(stmt)
        logger.warning(
            "Tabelle destinazione svuotate: %s", ", ".join(ordered_for_truncate)
        )

    def _reflect_table(self, engine: Engine, table_name: str) -> Table:
        metadata = MetaData()
        return Table(table_name, metadata, autoload_with=engine)

    def migrate_table(self, table_name: str) -> int:
        """
        Copia una singola tabella dalla sorgente alla destinazione.
        :return: numero di righe elaborate
        """
        if self.upsert and table_name in TABLE_CONFLICT_COLUMNS:
            return self._migrate_table_upsert(table_name)
        return self._migrate_table_insert(table_name)

    def _migrate_table_insert(self, table_name: str) -> int:
        if not self._table_exists(self.source_engine, table_name):
            logger.warning("Tabella '%s' assente in sorgente, skip.", table_name)
            return 0

        self.ensure_target_schema()
        source_table = self._reflect_table(self.source_engine, table_name)
        target_table = self._reflect_table(self.target_engine, table_name)

        inserted = 0
        with self.source_engine.connect() as source_conn:
            result = source_conn.execution_options(
                stream_results=True
            ).execute(select(source_table))

            while True:
                rows = result.fetchmany(self.batch_size)
                if not rows:
                    break

                payload = [dict(row._mapping) for row in rows]
                with self.target_engine.begin() as target_conn:
                    target_conn.execute(target_table.insert(), payload)

                inserted += len(payload)
                logger.info(
                    "Tabella '%s': inserite %s righe (totale %s)",
                    table_name,
                    len(payload),
                    inserted,
                )

        return inserted

    def _migrate_table_upsert(self, table_name: str) -> int:
        """Inserisce o aggiorna righe esistenti (adatto al cron giornaliero)."""
        if not self._table_exists(self.source_engine, table_name):
            logger.warning("Tabella '%s' assente in sorgente, skip.", table_name)
            return 0

        conflict_cols = TABLE_CONFLICT_COLUMNS[table_name]
        self.ensure_target_schema()
        source_table = self._reflect_table(self.source_engine, table_name)
        target_table = self._reflect_table(self.target_engine, table_name)

        processed = 0
        with self.source_engine.connect() as source_conn:
            result = source_conn.execution_options(
                stream_results=True
            ).execute(select(source_table))

            while True:
                rows = result.fetchmany(self.batch_size)
                if not rows:
                    break

                payload = [dict(row._mapping) for row in rows]
                stmt = pg_insert(target_table).values(payload)
                update_columns = {
                    col.name: stmt.excluded[col.name]
                    for col in target_table.columns
                    if col.name not in conflict_cols
                }
                stmt = stmt.on_conflict_do_update(
                    index_elements=conflict_cols,
                    set_=update_columns,
                )
                with self.target_engine.begin() as target_conn:
                    target_conn.execute(stmt)

                processed += len(payload)
                logger.info(
                    "Tabella '%s': upsert %s righe (totale %s)",
                    table_name,
                    len(payload),
                    processed,
                )

        return processed

    def migrate_all(self) -> dict[str, int]:
        """
        Esegue la migrazione completa nell'ordine definito.
        :return: dizionario tabella -> righe copiate
        """
        if self.source_url == self.target_url:
            raise ValueError(
                "SOURCE e TARGET hanno la stessa URL. "
                "Imposta DATABASE_SOURCE_URL e DATABASE_TARGET_URL diversi."
            )

        logger.info("Sorgente: %s", self._mask_url(self.source_url))
        logger.info("Destinazione: %s", self._mask_url(self.target_url))

        self._resolve_tables()
        self.ensure_target_schema()

        if self.clear_target:
            self.clear_target_tables()

        summary: dict[str, int] = {}
        for table_name in self.tables:
            try:
                count = self.migrate_table(table_name)
                summary[table_name] = count
            except SQLAlchemyError as exc:
                logger.error(
                    "Errore migrazione tabella '%s': %s", table_name, exc
                )
                raise

        total = sum(summary.values())
        logger.info("Migrazione completata. Righe totali copiate: %s", total)
        for table_name, count in summary.items():
            logger.info("  - %s: %s", table_name, count)

        return summary

    def verify_migration(self) -> dict[str, dict[str, int]]:
        """
        Confronta i conteggi righe sorgente vs destinazione per ogni tabella.
        """
        report: dict[str, dict[str, int]] = {}
        for table_name in self.tables:
            if not self._table_exists(self.source_engine, table_name):
                continue
            source_count = self._count_rows(self.source_engine, table_name)
            target_count = (
                self._count_rows(self.target_engine, table_name)
                if self._table_exists(self.target_engine, table_name)
                else 0
            )
            report[table_name] = {
                "source": source_count,
                "target": target_count,
                "match": source_count == target_count,
            }
        return report

    def _count_rows(self, engine: Engine, table_name: str) -> int:
        with engine.connect() as conn:
            return conn.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar_one()


def run_migration(
    clear_target: bool = False,
    upsert: bool = False,
    batch_size: int = 500,
    tables: Optional[Iterable[str]] = None,
) -> dict[str, int]:
    migrator = DatabaseMigrator(
        clear_target=clear_target,
        upsert=upsert,
        batch_size=batch_size,
        tables=tables,
    )
    summary = migrator.migrate_all()
    report = migrator.verify_migration()
    for table_name, counts in report.items():
        status = "OK" if counts["match"] else "DIFF"
        logger.info(
            "Verifica %s [%s]: source=%s target=%s",
            table_name,
            status,
            counts["source"],
            counts["target"],
        )
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Migra tennis_db da PostgreSQL sorgente a destinazione."
    )
    parser.add_argument(
        "--clear-target",
        action="store_true",
        help="Svuota le tabelle di destinazione prima della copia.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Righe per batch (default: 500).",
    )
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="Usa INSERT ... ON CONFLICT UPDATE (consigliato per sync giornaliero).",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        default=None,
        help="Sottoinsieme tabelle da migrare (es. fixture).",
    )
    args = parser.parse_args()
    run_migration(
        clear_target=args.clear_target,
        upsert=args.upsert,
        batch_size=args.batch_size,
        tables=args.tables,
    )
