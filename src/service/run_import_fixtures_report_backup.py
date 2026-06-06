import argparse
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse

from src.repository.base.repository_db import DATABASE_URL
from src.service.import_fixtures import calculate_date, import_fixtures_by_params


DEFAULT_REPORT_DIR = Path("reports")
DEFAULT_BACKUP_DIR = Path("backups")


def utc_now():
    return datetime.now(timezone.utc)


def format_timestamp(value):
    return value.strftime("%Y%m%d_%H%M%S")


def mask_database_url(database_url):
    parsed = urlparse(database_url)
    if not parsed.password:
        return database_url

    username = unquote(parsed.username) if parsed.username else ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    auth = f"{username}:****@" if username else "****@"
    return urlunparse(parsed._replace(netloc=f"{auth}{host}{port}"))


def backup_database(database_url=DATABASE_URL, backup_dir=DEFAULT_BACKUP_DIR, timestamp=None):
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = timestamp or format_timestamp(utc_now())

    parsed = urlparse(database_url)
    if parsed.scheme.startswith("sqlite"):
        source_path = Path(parsed.path)
        if not source_path.exists():
            raise RuntimeError(f"Database SQLite non trovato: {source_path}")
        backup_path = backup_dir / f"{source_path.stem}_{timestamp}{source_path.suffix}"
        shutil.copy2(source_path, backup_path)
        return {
            "status": "success",
            "path": str(backup_path),
            "size_bytes": backup_path.stat().st_size,
            "method": "sqlite_copy",
        }

    if not parsed.scheme.startswith("postgresql"):
        raise RuntimeError(f"Backup non supportato per database URL: {mask_database_url(database_url)}")

    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise RuntimeError("pg_dump non trovato: installare il client PostgreSQL per creare il backup")

    database_name = unquote(parsed.path.lstrip("/"))
    if not database_name:
        raise RuntimeError("Nome database PostgreSQL mancante nella DATABASE_URL")

    backup_path = backup_dir / f"{database_name}_{timestamp}.sql"
    command = [pg_dump, "--format=plain", "--file", str(backup_path)]
    if parsed.hostname:
        command.extend(["--host", parsed.hostname])
    if parsed.port:
        command.extend(["--port", str(parsed.port)])
    if parsed.username:
        command.extend(["--username", unquote(parsed.username)])
    command.append(database_name)

    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)

    result = subprocess.run(command, capture_output=True, env=env, text=True)
    if result.returncode != 0:
        if backup_path.exists():
            backup_path.unlink()
        error = result.stderr.strip() or result.stdout.strip() or "Errore sconosciuto durante pg_dump"
        raise RuntimeError(error)

    return {
        "status": "success",
        "path": str(backup_path),
        "size_bytes": backup_path.stat().st_size,
        "method": "pg_dump",
    }


def write_report(report_dir, timestamp, started_at, finished_at, params, import_stats, backup_result, success):
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"import_fixtures_report_{timestamp}.txt"

    lines = [
        "Report import_fixtures",
        "======================",
        f"Inizio UTC: {started_at.isoformat()}",
        f"Fine UTC: {finished_at.isoformat()}",
        f"Esito generale: {'OK' if success else 'KO'}",
        "",
        "Parametri import:",
        f"- date_start: {params.get('date_start')}",
        f"- date_stop: {params.get('date_stop')}",
        "",
        "Risultato import:",
        f"- stato: {import_stats.get('status')}",
        f"- fixture ricevute: {import_stats.get('fixtures_received')}",
        f"- fixture gia presenti: {import_stats.get('fixtures_already_present')}",
        f"- fixture importate: {import_stats.get('fixtures_imported')}",
        f"- fixture arricchite con odds: {import_stats.get('odds_enriched')}",
        "",
        "Backup database:",
        f"- stato: {backup_result.get('status')}",
        f"- metodo: {backup_result.get('method', '-')}",
        f"- file: {backup_result.get('path', '-')}",
        f"- dimensione byte: {backup_result.get('size_bytes', '-')}",
    ]

    errors = list(import_stats.get("errors") or [])
    if backup_result.get("error"):
        errors.append(f"Backup database: {backup_result['error']}")
    if errors:
        lines.extend(["", "Errori:"])
        lines.extend(f"- {error}" for error in errors)

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def run(date_start=None, date_stop=None, report_dir=DEFAULT_REPORT_DIR, backup_dir=DEFAULT_BACKUP_DIR):
    started_at = utc_now()
    timestamp = format_timestamp(started_at)

    if not date_start or not date_stop:
        default_start, default_stop = calculate_date()
        date_start = date_start or default_start
        date_stop = date_stop or default_stop

    params = {"date_start": date_start, "date_stop": date_stop}
    import_stats = import_fixtures_by_params(params)

    try:
        backup_result = backup_database(backup_dir=backup_dir, timestamp=timestamp)
    except Exception as exc:
        backup_result = {"status": "failed", "error": str(exc)}

    success = import_stats.get("status") == "success" and backup_result.get("status") == "success"
    report_path = write_report(
        report_dir=report_dir,
        timestamp=timestamp,
        started_at=started_at,
        finished_at=utc_now(),
        params=params,
        import_stats=import_stats,
        backup_result=backup_result,
        success=success,
    )

    return {
        "success": success,
        "report_path": str(report_path),
        "import": import_stats,
        "backup": backup_result,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Esegue import_fixtures, backup DB e report txt.")
    parser.add_argument("--date-start", dest="date_start", help="Data inizio import, formato YYYY-MM-DD")
    parser.add_argument("--date-stop", dest="date_stop", help="Data fine import, formato YYYY-MM-DD")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Directory report txt")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR), help="Directory backup DB")
    return parser.parse_args()


def main():
    args = parse_args()
    result = run(
        date_start=args.date_start,
        date_stop=args.date_stop,
        report_dir=args.report_dir,
        backup_dir=args.backup_dir,
    )
    print(f"Report creato: {result['report_path']}")
    if result["backup"].get("path"):
        print(f"Backup creato: {result['backup']['path']}")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
