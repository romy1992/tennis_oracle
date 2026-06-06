#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "properties" / "config.env"
REPORTS_DIR = ROOT_DIR / "reports"
BACKUPS_DIR = ROOT_DIR / "backups"
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/tennis_db"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@dataclass
class StepResult:
    name: str
    ok: bool
    details: str


class CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def lines(self, database_url: str) -> list[str]:
        formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
        return [sanitize(formatter.format(record), database_url) for record in self.records]

    def has_errors(self) -> bool:
        return any(record.levelno >= logging.ERROR for record in self.records)


def sanitize(value: str, database_url: str | None = None) -> str:
    sanitized = value
    if database_url:
        sanitized = sanitized.replace(database_url, mask_database_url(database_url))
    sanitized = re.sub(r"(?i)(APIkey=)[^&\s]+", r"\1***", sanitized)
    return sanitized


def mask_database_url(database_url: str) -> str:
    try:
        return str(make_url(database_url).set(password="***"))
    except Exception:
        return "***"


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def load_database_url() -> str:
    load_dotenv(dotenv_path=CONFIG_PATH)
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("DATABASE_SOURCE_URL")
        or DEFAULT_DATABASE_URL
    )


def current_branch() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=ROOT_DIR,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def ensure_schema(database_url: str) -> None:
    from src.entity import Event, Fixture, Player, Standing, Tournament
    from src.entity.base import Base

    _ = (Event, Fixture, Player, Standing, Tournament)
    engine = create_engine(database_url)
    Base.metadata.create_all(bind=engine)


def count_rows(database_url: str, table_name: str) -> int | None:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        if table_name not in inspect(connection).get_table_names():
            return None
        return connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()


def backup_database(database_url: str, backup_path: Path) -> int:
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise RuntimeError("pg_dump non trovato nel PATH")

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            pg_dump,
            f"--dbname={database_url}",
            "--format=plain",
            "--no-owner",
            "--no-privileges",
            f"--file={backup_path}",
        ],
        cwd=ROOT_DIR,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise RuntimeError(sanitize(output.strip(), database_url) or "pg_dump fallito")
    return backup_path.stat().st_size


def run_import(days_back_start: int, days_back_stop: int) -> None:
    from src.service.import_fixtures import run_daily_fixture_import

    run_daily_fixture_import(
        days_back_start=days_back_start,
        days_back_stop=days_back_stop,
    )


def write_report(
    report_path: Path,
    database_url: str,
    generated_at: str,
    branch: str,
    date_start: str,
    date_stop: str,
    fixture_count_before: int | None,
    fixture_count_after: int | None,
    steps: Iterable[StepResult],
    log_lines: Iterable[str],
    success: bool,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    delta = (
        fixture_count_after - fixture_count_before
        if fixture_count_before is not None and fixture_count_after is not None
        else None
    )
    lines = [
        "Report import_fixtures",
        "======================",
        f"Generated at (UTC): {generated_at}",
        f"Branch: {branch}",
        f"Database: {mask_database_url(database_url)}",
        f"Date range: {date_start} -> {date_stop}",
        f"Status: {'OK' if success else 'FAILED'}",
        "",
        "Fixture counts",
        "--------------",
        f"Before import: {fixture_count_before if fixture_count_before is not None else 'n/a'}",
        f"After import: {fixture_count_after if fixture_count_after is not None else 'n/a'}",
        f"Delta: {delta if delta is not None else 'n/a'}",
        "",
        "Steps",
        "-----",
    ]
    for step in steps:
        lines.append(f"- {step.name}: {'OK' if step.ok else 'FAILED'} - {step.details}")

    lines.extend(["", "Captured logs", "-------------"])
    captured = list(log_lines)
    lines.extend(captured if captured else ["No logs captured."])
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Esegue import_fixtures, backup DB pre/post e report testuale."
    )
    parser.add_argument("--days-back-start", type=int, default=1)
    parser.add_argument("--days-back-stop", type=int, default=0)
    parser.add_argument("--timestamp", default=timestamp())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated_at = datetime.now(timezone.utc).isoformat()
    database_url = load_database_url()
    branch = current_branch()

    from src.service.import_fixtures import calculate_date

    date_start, date_stop = calculate_date(
        days_back_start=args.days_back_start,
        days_back_stop=args.days_back_stop,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"import_fixtures_report_{args.timestamp}.txt"
    pre_backup_path = BACKUPS_DIR / f"tennis_db_pre_import_{args.timestamp}.sql"
    post_backup_path = BACKUPS_DIR / f"tennis_db_post_import_{args.timestamp}.sql"

    capture_handler = CaptureHandler()
    root_logger = logging.getLogger()
    root_logger.addHandler(capture_handler)
    root_logger.setLevel(logging.INFO)

    steps: list[StepResult] = []
    fixture_count_before: int | None = None
    fixture_count_after: int | None = None

    def run_step(name: str, action) -> bool:
        try:
            details = action()
            steps.append(StepResult(name=name, ok=True, details=str(details)))
            return True
        except Exception as exc:
            details = sanitize(f"{exc}\n{traceback.format_exc()}", database_url)
            steps.append(StepResult(name=name, ok=False, details=details))
            return False

    def count_before_action() -> str:
        nonlocal fixture_count_before
        fixture_count_before = count_rows(database_url, "fixture")
        return "conteggio fixture iniziale completato"

    def count_after_action() -> str:
        nonlocal fixture_count_after
        fixture_count_after = count_rows(database_url, "fixture")
        return "conteggio fixture finale completato"

    schema_ok = run_step(
        "ensure_schema",
        lambda: (ensure_schema(database_url), "schema verificato/creato")[1],
    )

    if schema_ok:
        run_step(
            "count_before",
            count_before_action,
        )

        run_step(
            "backup_before_import",
            lambda: f"{pre_backup_path.relative_to(ROOT_DIR)} ({backup_database(database_url, pre_backup_path)} bytes)",
        )

        run_step(
            "import_fixtures",
            lambda: (run_import(args.days_back_start, args.days_back_stop), "import completato")[1],
        )

        run_step(
            "count_after",
            count_after_action,
        )

        run_step(
            "backup_after_import",
            lambda: f"{post_backup_path.relative_to(ROOT_DIR)} ({backup_database(database_url, post_backup_path)} bytes)",
        )

    success = all(step.ok for step in steps) and not capture_handler.has_errors()
    if capture_handler.has_errors():
        steps.append(
            StepResult(
                name="captured_log_errors",
                ok=False,
                details="Sono presenti log ERROR durante l'import.",
            )
        )
        success = False

    write_report(
        report_path=report_path,
        database_url=database_url,
        generated_at=generated_at,
        branch=branch,
        date_start=date_start,
        date_stop=date_stop,
        fixture_count_before=fixture_count_before,
        fixture_count_after=fixture_count_after,
        steps=steps,
        log_lines=capture_handler.lines(database_url),
        success=success,
    )
    print(f"Report scritto: {report_path.relative_to(ROOT_DIR)}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
