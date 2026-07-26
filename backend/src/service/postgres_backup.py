"""PostgreSQL backup / restore helpers (pg_dump / pg_restore).

Credentials come from the environment or DATABASE_URL. Passwords are never
written into scripts, argv, log lines, or backup filenames.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = "backups"
DEFAULT_RETENTION_DAYS = 7
DUMP_SUFFIX = ".dump"
GPG_SUFFIX = ".gpg"
SHA_SUFFIX = ".sha256"
FILENAME_RE = re.compile(
    r"^(?P<db>[A-Za-z0-9_]+)_(?P<ts>\d{8}_\d{6})\.dump(?:\.gpg)?$"
)


@dataclass(frozen=True)
class DbTarget:
    host: str
    port: str
    user: str
    password: str
    database: str

    @property
    def safe_label(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class BackupResult:
    ok: bool
    archive_path: Path | None
    checksum_path: Path | None
    encrypted: bool
    removed_count: int
    message: str
    warnings: list[str]


@dataclass(frozen=True)
class RestoreResult:
    ok: bool
    mode: str
    target_database: str | None
    message: str
    warnings: list[str]


class BackupError(RuntimeError):
    """Raised for expected operational failures (missing tools, bad config)."""


def parse_database_url(url: str) -> DbTarget:
    raw = (url or "").strip()
    if not raw:
        raise BackupError("DATABASE_URL is empty")
    parsed = urlparse(raw)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise BackupError(
            f"Unsupported DATABASE_URL scheme '{parsed.scheme or '-'}' "
            "(expected postgresql)"
        )
    database = unquote((parsed.path or "").lstrip("/"))
    if not database:
        raise BackupError("DATABASE_URL is missing the database name")
    if "/" in database or "?" in database:
        database = database.split("?", 1)[0]
    user = unquote(parsed.username or "")
    if not user:
        raise BackupError("DATABASE_URL is missing the user")
    return DbTarget(
        host=parsed.hostname or "localhost",
        port=str(parsed.port or 5432),
        user=user,
        password=unquote(parsed.password or ""),
        database=database,
    )


def resolve_db_target(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> DbTarget:
    """Resolve connection from DATABASE_URL or classic libpq PG* variables."""
    environ = env if env is not None else os.environ
    url = (database_url or environ.get("DATABASE_URL") or "").strip()
    if url:
        return parse_database_url(url)

    database = (environ.get("PGDATABASE") or environ.get("POSTGRES_DB") or "").strip()
    user = (environ.get("PGUSER") or environ.get("POSTGRES_USER") or "").strip()
    if not database or not user:
        raise BackupError(
            "Set DATABASE_URL or PGUSER/PGDATABASE (and related PG* / POSTGRES_* vars)"
        )
    return DbTarget(
        host=(environ.get("PGHOST") or "localhost").strip(),
        port=(environ.get("PGPORT") or environ.get("POSTGRES_PORT") or "5432").strip(),
        user=user,
        password=environ.get("PGPASSWORD") or environ.get("POSTGRES_PASSWORD") or "",
        database=database,
    )


def libpq_env(target: DbTarget, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Child-process env for libpq. Password stays in env, not argv."""
    out = dict(base if base is not None else os.environ)
    out["PGHOST"] = target.host
    out["PGPORT"] = target.port
    out["PGUSER"] = target.user
    out["PGDATABASE"] = target.database
    if target.password:
        out["PGPASSWORD"] = target.password
    else:
        out.pop("PGPASSWORD", None)
    return out


def which_tool(name: str) -> str | None:
    return shutil.which(name)


def require_tool(name: str) -> str:
    path = which_tool(name)
    if not path:
        raise BackupError(f"Required tool not found on PATH: {name}")
    return path


def utc_timestamp(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")


def backup_filename(database: str, ts: str, *, encrypted: bool) -> str:
    safe_db = re.sub(r"[^A-Za-z0-9_]", "_", database)
    name = f"{safe_db}_{ts}{DUMP_SUFFIX}"
    return f"{name}{GPG_SUFFIX}" if encrypted else name


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_checksum(archive: Path) -> Path:
    checksum_path = Path(str(archive) + SHA_SUFFIX)
    digest = sha256_file(archive)
    checksum_path.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return checksum_path


def verify_checksum(archive: Path, checksum_path: Path | None = None) -> None:
    side = checksum_path or Path(str(archive) + SHA_SUFFIX)
    if not side.is_file():
        raise BackupError(f"Checksum file missing: {side}")
    line = side.read_text(encoding="utf-8").strip().split()
    if not line:
        raise BackupError(f"Checksum file empty: {side}")
    expected = line[0].lower()
    actual = sha256_file(archive)
    if actual != expected:
        raise BackupError(
            f"Checksum mismatch for {archive.name}: expected {expected}, got {actual}"
        )


def run_command(
    args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    logger.info("Running: %s", " ".join(args))
    completed = subprocess.run(
        list(args),
        env=dict(env) if env is not None else None,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"exit {completed.returncode}"
        # Never echo env; redact obvious password= fragments if tools print them.
        detail = re.sub(r"(password|pwd)=([^\s]+)", r"\1=***", detail, flags=re.I)
        raise BackupError(f"Command failed ({args[0]}): {detail}")
    return completed


def create_custom_dump(
    target: DbTarget,
    output: Path,
    *,
    pg_dump_bin: str | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    pg_dump = pg_dump_bin or require_tool("pg_dump")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Custom format with built-in compression; good for pg_restore --list integrity.
    args = [
        pg_dump,
        "--format=custom",
        "--compress=9",
        "--no-password",
        "--file",
        str(output),
        "--dbname",
        target.database,
    ]
    run_command(args, env=libpq_env(target, env))


def verify_dump_integrity(
    archive: Path,
    *,
    encrypted: bool,
    pg_restore_bin: str | None = None,
    gpg_bin: str | None = None,
    passphrase_file: str | None = None,
    work_dir: Path | None = None,
) -> None:
    if not archive.is_file() or archive.stat().st_size <= 0:
        raise BackupError(f"Backup archive missing or empty: {archive}")

    if encrypted:
        gpg = gpg_bin or require_tool("gpg")
        # Packet listing avoids loading the full plaintext into memory.
        run_command([gpg, "--batch", "--list-packets", str(archive)], check=True)
        if passphrase_file or work_dir is not None:
            staging = work_dir or (archive.parent / ".restore_work")
            staging.mkdir(parents=True, exist_ok=True)
            plain = decrypt_archive_if_needed(
                archive,
                work_dir=staging,
                passphrase_file=passphrase_file,
            )
            try:
                verify_dump_integrity(plain, encrypted=False, pg_restore_bin=pg_restore_bin)
            finally:
                if plain != archive and plain.is_file():
                    plain.unlink(missing_ok=True)
        return

    pg_restore = pg_restore_bin or require_tool("pg_restore")
    run_command(
        [pg_restore, "--list", str(archive)],
        check=True,
    )


def encrypt_file_gpg(
    source: Path,
    dest: Path,
    *,
    recipient: str | None = None,
    passphrase_file: str | None = None,
    gpg_bin: str | None = None,
) -> None:
    gpg = gpg_bin or require_tool("gpg")
    if recipient:
        args = [
            gpg,
            "--batch",
            "--yes",
            "--trust-model",
            "always",
            "--encrypt",
            "--recipient",
            recipient,
            "--output",
            str(dest),
            str(source),
        ]
    elif passphrase_file:
        if not Path(passphrase_file).is_file():
            raise BackupError(f"BACKUP_GPG_PASSPHRASE_FILE not found: {passphrase_file}")
        args = [
            gpg,
            "--batch",
            "--yes",
            "--symmetric",
            "--cipher-algo",
            "AES256",
            "--pinentry-mode",
            "loopback",
            "--passphrase-file",
            passphrase_file,
            "--output",
            str(dest),
            str(source),
        ]
    else:
        raise BackupError(
            "Encryption enabled but neither BACKUP_GPG_RECIPIENT nor "
            "BACKUP_GPG_PASSPHRASE_FILE is set"
        )
    run_command(args, check=True)


def apply_retention(
    backup_dir: Path,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> list[Path]:
    if retention_days < 0:
        raise BackupError("BACKUP_RETENTION_DAYS must be >= 0")
    if retention_days == 0:
        return []
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    cutoff = moment - timedelta(days=retention_days)
    removed: list[Path] = []
    if not backup_dir.is_dir():
        return removed
    for path in sorted(backup_dir.iterdir()):
        if not path.is_file():
            continue
        match = FILENAME_RE.match(path.name)
        if not match:
            continue
        try:
            file_ts = datetime.strptime(match.group("ts"), "%Y%m%d_%H%M%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        if file_ts >= cutoff:
            continue
        path.unlink(missing_ok=True)
        removed.append(path)
        side = Path(str(path) + SHA_SUFFIX)
        if side.is_file():
            side.unlink(missing_ok=True)
            removed.append(side)
    return removed


def perform_backup(
    *,
    target: DbTarget,
    backup_dir: Path,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    encrypt: bool = False,
    gpg_recipient: str | None = None,
    gpg_passphrase_file: str | None = None,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> BackupResult:
    warnings: list[str] = []
    ts = utc_timestamp(now)
    backup_dir.mkdir(parents=True, exist_ok=True)
    plain_name = backup_filename(target.database, ts, encrypted=False)
    plain_path = backup_dir / plain_name
    final_path = backup_dir / backup_filename(target.database, ts, encrypted=encrypt)

    create_custom_dump(target, plain_path, env=env)

    encrypted = False
    try:
        if encrypt:
            encrypt_file_gpg(
                plain_path,
                final_path,
                recipient=(gpg_recipient or "").strip() or None,
                passphrase_file=(gpg_passphrase_file or "").strip() or None,
            )
            plain_path.unlink(missing_ok=True)
            encrypted = True
        else:
            final_path = plain_path

        verify_dump_integrity(
            final_path,
            encrypted=encrypted,
            passphrase_file=(gpg_passphrase_file or "").strip() or None,
        )
        checksum_path = write_checksum(final_path)
        verify_checksum(final_path, checksum_path)
        removed = apply_retention(backup_dir, retention_days=retention_days, now=now)
    except Exception:
        # Best-effort cleanup of a failed partial archive.
        if plain_path.is_file() and plain_path != final_path:
            plain_path.unlink(missing_ok=True)
        if final_path.is_file():
            final_path.unlink(missing_ok=True)
        raise

    msg = (
        f"Backup OK target={target.safe_label} file={final_path.name} "
        f"encrypted={encrypted} removed_old={len(removed)}"
    )
    logger.info(msg)
    return BackupResult(
        ok=True,
        archive_path=final_path,
        checksum_path=checksum_path,
        encrypted=encrypted,
        removed_count=len(removed),
        message=msg,
        warnings=warnings,
    )


def _ensure_database_exists(
    target: DbTarget,
    database: str,
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    psql = require_tool("psql")
    admin = DbTarget(
        host=target.host,
        port=target.port,
        user=target.user,
        password=target.password,
        database="postgres",
    )
    exists = run_command(
        [
            psql,
            "--no-password",
            "-d",
            "postgres",
            "-tAc",
            f"SELECT 1 FROM pg_database WHERE datname='{database}'",
        ],
        env=libpq_env(admin, env),
        check=True,
    )
    if (exists.stdout or "").strip() == "1":
        return
    # Identifier: only allow safe names we generate / user passes explicitly.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database):
        raise BackupError(f"Unsafe database name for CREATE DATABASE: {database}")
    run_command(
        [
            psql,
            "--no-password",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            f'CREATE DATABASE "{database}"',
        ],
        env=libpq_env(admin, env),
        check=True,
    )


def _drop_and_recreate_database(
    target: DbTarget,
    database: str,
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database):
        raise BackupError(f"Unsafe database name: {database}")
    psql = require_tool("psql")
    admin = DbTarget(
        host=target.host,
        port=target.port,
        user=target.user,
        password=target.password,
        database="postgres",
    )
    env_admin = libpq_env(admin, env)
    run_command(
        [
            psql,
            "--no-password",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            (
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{database}' AND pid <> pg_backend_pid();"
            ),
        ],
        env=env_admin,
        check=False,
    )
    run_command(
        [
            psql,
            "--no-password",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            f'DROP DATABASE IF EXISTS "{database}"',
        ],
        env=env_admin,
        check=True,
    )
    run_command(
        [
            psql,
            "--no-password",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            f'CREATE DATABASE "{database}"',
        ],
        env=env_admin,
        check=True,
    )


def decrypt_archive_if_needed(
    archive: Path,
    *,
    work_dir: Path,
    passphrase_file: str | None = None,
) -> Path:
    if not archive.name.endswith(GPG_SUFFIX):
        return archive
    gpg = require_tool("gpg")
    dest = work_dir / archive.name[: -len(GPG_SUFFIX)]
    args = [gpg, "--batch", "--yes"]
    if passphrase_file:
        args.extend(
            ["--pinentry-mode", "loopback", "--passphrase-file", passphrase_file]
        )
    args.extend(["--decrypt", "--output", str(dest), str(archive)])
    run_command(args, check=True)
    return dest


def perform_restore(
    *,
    archive: Path,
    target: DbTarget,
    mode: str,
    target_database: str | None = None,
    overwrite_source: bool = False,
    yes: bool = False,
    gpg_passphrase_file: str | None = None,
    work_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> RestoreResult:
    """Restore modes: dry-run | test | overwrite.

    - dry-run: checksum + pg_restore --list only (no DB writes)
    - test: restore into an alternate DB (default ``{source}_restore_test``)
    - overwrite: restore into the source database (requires flags)
    """
    warnings: list[str] = []
    if not archive.is_file():
        raise BackupError(f"Backup archive not found: {archive}")

    verify_checksum(archive)
    encrypted = archive.name.endswith(GPG_SUFFIX)

    if mode == "dry-run":
        staging = work_dir or (archive.parent / ".restore_work")
        verify_dump_integrity(
            archive,
            encrypted=encrypted,
            passphrase_file=gpg_passphrase_file,
            work_dir=staging if encrypted else None,
        )
        msg = f"Dry-run OK archive={archive.name} source={target.safe_label}"
        logger.info(msg)
        return RestoreResult(
            ok=True,
            mode=mode,
            target_database=None,
            message=msg,
            warnings=warnings,
        )

    if mode == "test":
        dest_db = (target_database or f"{target.database}_restore_test").strip()
        if dest_db == target.database:
            raise BackupError(
                "Test restore target must differ from the source database; "
                "use --mode overwrite with --overwrite-source for that"
            )
    elif mode == "overwrite":
        if not overwrite_source or not yes:
            raise BackupError(
                "Refusing to overwrite the source database without "
                "--overwrite-source and --yes"
            )
        dest_db = (target_database or target.database).strip()
        if dest_db != target.database and not yes:
            raise BackupError("Unexpected target database for overwrite mode")
    else:
        raise BackupError(f"Unknown restore mode: {mode}")

    staging = work_dir or (archive.parent / ".restore_work")
    staging.mkdir(parents=True, exist_ok=True)
    dump_path = decrypt_archive_if_needed(
        archive,
        work_dir=staging,
        passphrase_file=gpg_passphrase_file,
    )
    verify_dump_integrity(dump_path, encrypted=False)

    if mode == "overwrite":
        _drop_and_recreate_database(target, dest_db, env=env)
    else:
        _ensure_database_exists(target, dest_db, env=env)

    pg_restore = require_tool("pg_restore")
    restore_target = DbTarget(
        host=target.host,
        port=target.port,
        user=target.user,
        password=target.password,
        database=dest_db,
    )
    # --clean --if-exists is safe on a freshly created empty DB; kept for re-runs on test DB.
    completed = run_command(
        [
            pg_restore,
            "--no-password",
            "--verbose",
            "--clean",
            "--if-exists",
            "--dbname",
            dest_db,
            str(dump_path),
        ],
        env=libpq_env(restore_target, env),
        check=False,
    )
    # pg_restore can return 1 for non-fatal warnings (e.g. role differences).
    if completed.returncode > 1:
        detail = (completed.stderr or completed.stdout or "").strip()
        detail = re.sub(r"(password|pwd)=([^\s]+)", r"\1=***", detail, flags=re.I)
        raise BackupError(f"pg_restore failed: {detail}")
    if completed.returncode == 1:
        warnings.append("pg_restore completed with warnings (exit 1)")

    if dump_path != archive and dump_path.is_file():
        dump_path.unlink(missing_ok=True)

    msg = (
        f"Restore OK mode={mode} archive={archive.name} "
        f"target_db={dest_db} host={target.host}:{target.port}"
    )
    logger.info(msg)
    return RestoreResult(
        ok=True,
        mode=mode,
        target_database=dest_db,
        message=msg,
        warnings=warnings,
    )


def result_to_dict(result: BackupResult | RestoreResult) -> dict[str, Any]:
    if isinstance(result, BackupResult):
        return {
            "ok": result.ok,
            "archive_path": str(result.archive_path) if result.archive_path else None,
            "checksum_path": str(result.checksum_path) if result.checksum_path else None,
            "encrypted": result.encrypted,
            "removed_count": result.removed_count,
            "message": result.message,
            "warnings": result.warnings,
        }
    return {
        "ok": result.ok,
        "mode": result.mode,
        "target_database": result.target_database,
        "message": result.message,
        "warnings": result.warnings,
    }
