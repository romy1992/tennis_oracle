"""CLI: PostgreSQL logical backup with retention, checksum, optional GPG.

Examples:
  python -m backend.src.jobs.run_db_backup
  python -m backend.src.jobs.run_db_backup --alert
  python -m backend.src.jobs.run_db_backup --encrypt --retention-days 14

Exit codes: 0 ok, 1 ok with warnings, 2 failure.
Credentials: DATABASE_URL or PG* / POSTGRES_* env vars (never hard-coded).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from backend.src.app.core.config import get_settings
from backend.src.app.observability.alerts import send_admin_alert
from backend.src.app.observability.context import ensure_correlation_id
from backend.src.app.observability.setup import setup_observability
from backend.src.service.postgres_backup import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_RETENTION_DAYS,
    BackupError,
    perform_backup,
    resolve_db_target,
    result_to_dict,
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../properties/config.env")
ROOT_ENV = os.path.join(os.path.dirname(__file__), "../../../.env")
load_dotenv(dotenv_path=CONFIG_PATH)
load_dotenv(dotenv_path=ROOT_ENV)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backup PostgreSQL for tennis_oracle")
    parser.add_argument(
        "--backup-dir",
        default=os.getenv("BACKUP_DIR", DEFAULT_BACKUP_DIR),
        help="Directory for dump files (default: BACKUP_DIR or ./backups)",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=_env_int("BACKUP_RETENTION_DAYS", DEFAULT_RETENTION_DAYS),
        help="Delete matching dumps older than N days (0 = keep all)",
    )
    parser.add_argument(
        "--encrypt",
        action="store_true",
        default=_env_bool("BACKUP_ENCRYPT", False),
        help="Encrypt archive with GPG (recipient or passphrase file)",
    )
    parser.add_argument(
        "--no-encrypt",
        action="store_true",
        help="Disable encryption even if BACKUP_ENCRYPT=true",
    )
    parser.add_argument(
        "--gpg-recipient",
        default=os.getenv("BACKUP_GPG_RECIPIENT", "") or None,
        help="GPG public-key recipient (BACKUP_GPG_RECIPIENT)",
    )
    parser.add_argument(
        "--gpg-passphrase-file",
        default=os.getenv("BACKUP_GPG_PASSPHRASE_FILE", "") or None,
        help="File containing symmetric passphrase (never pass the secret itself)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL for this run (prefer env in cron)",
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        help="Send admin alert (Telegram/webhook) on failure",
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
    ensure_correlation_id(f"db-backup-{os.getpid()}")
    logger = logging.getLogger(__name__)

    encrypt = bool(args.encrypt) and not bool(args.no_encrypt)
    backup_dir = Path(args.backup_dir)
    if not backup_dir.is_absolute():
        backup_dir = Path.cwd() / backup_dir

    try:
        target = resolve_db_target(database_url=args.database_url)
        result = perform_backup(
            target=target,
            backup_dir=backup_dir,
            retention_days=args.retention_days,
            encrypt=encrypt,
            gpg_recipient=args.gpg_recipient,
            gpg_passphrase_file=args.gpg_passphrase_file,
        )
    except BackupError as exc:
        logger.error("db_backup failed: %s", exc)
        if args.alert:
            send_admin_alert(
                f"PostgreSQL backup FAILED: {exc}",
                severity="critical",
                dedupe_key="backup:failed:daily",
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
        logger.exception("db_backup unexpected error")
        if args.alert:
            send_admin_alert(
                f"PostgreSQL backup unexpected error: {exc}",
                severity="critical",
                dedupe_key="backup:failed:daily",
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
