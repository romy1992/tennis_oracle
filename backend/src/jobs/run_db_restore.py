"""CLI: PostgreSQL restore with dry-run / test DB / guarded overwrite.

Examples:
  # Integrity only — never touches a database
  python -m backend.src.jobs.run_db_restore --archive backups/tennis_db_….dump --mode dry-run

  # Restore into tennis_db_restore_test (safe rehearsal)
  python -m backend.src.jobs.run_db_restore --archive backups/tennis_db_….dump --mode test

  # Disaster recovery into the source DB (destructive)
  python -m backend.src.jobs.run_db_restore --archive … --mode overwrite --overwrite-source --yes

Exit codes: 0 ok, 1 ok with warnings, 2 failure.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from backend.src.app.core.config import get_settings
from backend.src.app.core.env_files import load_backend_env_files
from backend.src.app.observability.alerts import send_admin_alert
from backend.src.app.observability.context import ensure_correlation_id
from backend.src.app.observability.setup import setup_observability
from backend.src.service.postgres_backup import (
    BackupError,
    perform_restore,
    resolve_db_target,
    result_to_dict,
)

load_backend_env_files(override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Restore PostgreSQL for tennis_oracle")
    parser.add_argument(
        "--archive",
        required=True,
        help="Path to .dump or .dump.gpg archive",
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "test", "overwrite"),
        default="dry-run",
        help="dry-run (default), test (alternate DB), overwrite (source DB)",
    )
    parser.add_argument(
        "--target-db",
        default=None,
        help="Target database name (test default: {source}_restore_test)",
    )
    parser.add_argument(
        "--overwrite-source",
        action="store_true",
        help="Required with --mode overwrite to replace the source database",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive overwrite",
    )
    parser.add_argument(
        "--gpg-passphrase-file",
        default=os.getenv("BACKUP_GPG_PASSPHRASE_FILE", "") or None,
        help="Passphrase file for symmetric .gpg archives",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL (connection host/user; DB name is source identity)",
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        help="Send admin alert on failure",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print result JSON on stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_observability(settings)
    ensure_correlation_id(f"db-restore-{os.getpid()}")
    logger = logging.getLogger(__name__)

    archive = Path(args.archive)
    if not archive.is_absolute():
        archive = Path.cwd() / archive

    try:
        target = resolve_db_target(database_url=args.database_url)
        result = perform_restore(
            archive=archive,
            target=target,
            mode=args.mode,
            target_database=args.target_db,
            overwrite_source=bool(args.overwrite_source),
            yes=bool(args.yes),
            gpg_passphrase_file=args.gpg_passphrase_file,
        )
    except BackupError as exc:
        logger.error("db_restore failed: %s", exc)
        if args.alert:
            send_admin_alert(
                f"PostgreSQL restore FAILED: {exc}",
                severity="critical",
                dedupe_key="backup:restore:failed",
                telegram_bot_token=settings.telegram_bot_token,
                telegram_admin_chat_id=settings.telegram_admin_chat_id,
                webhook_url=settings.ops_alert_webhook_url,
                cooldown_seconds=settings.ops_alert_cooldown_seconds,
                enabled=settings.ops_alerts_enabled,
            )
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    except Exception as exc:
        logger.exception("db_restore unexpected error")
        if args.alert:
            send_admin_alert(
                f"PostgreSQL restore unexpected error: {exc}",
                severity="critical",
                dedupe_key="backup:restore:failed",
                telegram_bot_token=settings.telegram_bot_token,
                telegram_admin_chat_id=settings.telegram_admin_chat_id,
                webhook_url=settings.ops_alert_webhook_url,
                cooldown_seconds=settings.ops_alert_cooldown_seconds,
                enabled=settings.ops_alerts_enabled,
            )
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    payload = result_to_dict(result)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        logger.info(result.message)
        for warning in result.warnings:
            logger.warning(warning)

    return 1 if result.warnings else 0


if __name__ == "__main__":
    sys.exit(main())
