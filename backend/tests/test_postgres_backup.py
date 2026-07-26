"""Unit tests for PostgreSQL backup/restore helpers (no live Postgres required)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.src.jobs import run_db_backup, run_db_restore
from backend.src.service import postgres_backup as pb


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestParseAndResolve:
    def test_parse_database_url(self):
        target = pb.parse_database_url(
            "postgresql://alice%40x:s%3Bcret@db.example:6543/tennis_db"
        )
        assert target.user == "alice@x"
        assert target.password == "s;cret"
        assert target.host == "db.example"
        assert target.port == "6543"
        assert target.database == "tennis_db"
        assert "s;cret" not in target.safe_label

    def test_parse_rejects_sqlite(self):
        with pytest.raises(pb.BackupError, match="Unsupported"):
            pb.parse_database_url("sqlite://")

    def test_resolve_from_pg_env(self):
        target = pb.resolve_db_target(
            env={
                "PGHOST": "127.0.0.1",
                "PGPORT": "5433",
                "PGUSER": "postgres",
                "PGPASSWORD": "secret",
                "PGDATABASE": "tennis_db_staging",
            }
        )
        assert target.database == "tennis_db_staging"
        assert target.port == "5433"
        env = pb.libpq_env(target, base={})
        assert env["PGPASSWORD"] == "secret"
        assert "--password" not in env


class TestFilenamesChecksumRetention:
    def test_backup_filename_and_checksum(self, tmp_path: Path):
        name = pb.backup_filename("tennis_db", "20260726_101500", encrypted=False)
        assert name == "tennis_db_20260726_101500.dump"
        enc = pb.backup_filename("tennis_db", "20260726_101500", encrypted=True)
        assert enc.endswith(".dump.gpg")

        archive = tmp_path / name
        archive.write_bytes(b"dummy-dump-bytes")
        side = pb.write_checksum(archive)
        assert side.name.endswith(".sha256")
        pb.verify_checksum(archive, side)

        side.write_text("0" * 64 + "  " + name + "\n", encoding="utf-8")
        with pytest.raises(pb.BackupError, match="Checksum mismatch"):
            pb.verify_checksum(archive, side)

    def test_apply_retention(self, tmp_path: Path):
        now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
        old = tmp_path / "tennis_db_20260701_000000.dump"
        mid = tmp_path / "tennis_db_20260720_000000.dump"
        fresh = tmp_path / "tennis_db_20260725_000000.dump"
        noise = tmp_path / "notes.txt"
        for path in (old, mid, fresh, noise):
            path.write_bytes(b"x")
            if path.suffix == ".dump":
                pb.write_checksum(path)

        removed = pb.apply_retention(tmp_path, retention_days=7, now=now)
        removed_names = {p.name for p in removed}
        assert "tennis_db_20260701_000000.dump" in removed_names
        assert not old.exists()
        assert mid.exists()
        assert fresh.exists()
        assert noise.exists()


class TestPerformBackupRestoreGuards:
    def test_perform_backup_happy_path(self, tmp_path: Path):
        target = pb.DbTarget("localhost", "5432", "postgres", "x", "tennis_db")

        def fake_run(args, **kwargs):
            # pg_dump writes --file
            if args and Path(args[0]).name.startswith("pg_dump") or (
                len(args) > 1 and args[0].endswith("pg_dump")
            ):
                out = Path(args[args.index("--file") + 1])
                out.write_bytes(b"PGDUMP")
            return MagicMock(returncode=0, stdout="TOC\n", stderr="")

        with (
            patch.object(pb, "require_tool", side_effect=lambda n: n),
            patch.object(pb, "run_command", side_effect=fake_run),
        ):
            result = pb.perform_backup(
                target=target,
                backup_dir=tmp_path,
                retention_days=7,
                encrypt=False,
                now=datetime(2026, 7, 26, 10, 15, tzinfo=timezone.utc),
            )

        assert result.ok
        assert result.archive_path is not None
        assert result.archive_path.name == "tennis_db_20260726_101500.dump"
        assert result.checksum_path is not None
        assert result.checksum_path.is_file()

    def test_restore_refuses_overwrite_without_flags(self, tmp_path: Path):
        archive = tmp_path / "tennis_db_20260726_101500.dump"
        archive.write_bytes(b"PGDUMP")
        pb.write_checksum(archive)
        target = pb.DbTarget("localhost", "5432", "postgres", "x", "tennis_db")

        with (
            patch.object(pb, "require_tool", side_effect=lambda n: n),
            patch.object(pb, "run_command", return_value=MagicMock(returncode=0, stdout="", stderr="")),
            pytest.raises(pb.BackupError, match="overwrite-source"),
        ):
            pb.perform_restore(
                archive=archive,
                target=target,
                mode="overwrite",
                overwrite_source=False,
                yes=False,
            )

    def test_restore_dry_run_no_db_writes(self, tmp_path: Path):
        archive = tmp_path / "tennis_db_20260726_101500.dump"
        archive.write_bytes(b"PGDUMP")
        pb.write_checksum(archive)
        target = pb.DbTarget("localhost", "5432", "postgres", "x", "tennis_db")
        calls: list[list[str]] = []

        def capture(args, **kwargs):
            calls.append(list(args))
            return MagicMock(returncode=0, stdout="TOC\n", stderr="")

        with (
            patch.object(pb, "require_tool", side_effect=lambda n: n),
            patch.object(pb, "run_command", side_effect=capture),
        ):
            result = pb.perform_restore(
                archive=archive,
                target=target,
                mode="dry-run",
            )

        assert result.ok
        assert result.target_database is None
        assert any("pg_restore" in c[0] or c[0] == "pg_restore" for c in calls)
        assert not any("CREATE DATABASE" in " ".join(c) for c in calls)
        assert not any("--clean" in c for c in calls)

    def test_test_mode_rejects_same_db_name(self, tmp_path: Path):
        archive = tmp_path / "tennis_db_20260726_101500.dump"
        archive.write_bytes(b"PGDUMP")
        pb.write_checksum(archive)
        target = pb.DbTarget("localhost", "5432", "postgres", "x", "tennis_db")
        with pytest.raises(pb.BackupError, match="must differ"):
            pb.perform_restore(
                archive=archive,
                target=target,
                mode="test",
                target_database="tennis_db",
            )


class TestCliAndAssets:
    def test_backup_cli_failure_exit_code(self):
        with patch.object(
            run_db_backup,
            "resolve_db_target",
            side_effect=pb.BackupError("boom"),
        ):
            code = run_db_backup.main(["--json"])
        assert code == 2

    def test_restore_cli_dry_run_uses_module(self, tmp_path: Path):
        archive = tmp_path / "tennis_db_20260726_101500.dump"
        archive.write_bytes(b"PGDUMP")
        pb.write_checksum(archive)

        with (
            patch.object(
                run_db_restore,
                "resolve_db_target",
                return_value=pb.DbTarget("h", "5432", "u", "", "tennis_db"),
            ),
            patch.object(
                run_db_restore,
                "perform_restore",
                return_value=pb.RestoreResult(
                    ok=True,
                    mode="dry-run",
                    target_database=None,
                    message="ok",
                    warnings=[],
                ),
            ) as mocked,
        ):
            code = run_db_restore.main(
                ["--archive", str(archive), "--mode", "dry-run", "--json"]
            )
        assert code == 0
        mocked.assert_called_once()

    def test_scripts_and_docs_exist(self):
        required = [
            "backend/src/service/postgres_backup.py",
            "backend/src/jobs/run_db_backup.py",
            "backend/src/jobs/run_db_restore.py",
            "backend/scripts/backup_postgres.sh",
            "backend/scripts/backup_postgres.bat",
            "backend/scripts/restore_postgres.sh",
            "backend/scripts/restore_postgres.bat",
            "docs/BACKUP_DR.md",
        ]
        missing = [p for p in required if not (REPO_ROOT / p).is_file()]
        assert missing == [], missing

    def test_wrappers_have_no_hardcoded_passwords(self):
        for rel in (
            "backend/scripts/backup_postgres.sh",
            "backend/scripts/backup_postgres.bat",
            "backend/scripts/restore_postgres.sh",
            "backend/scripts/restore_postgres.bat",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "PGPASSWORD=" not in text
            assert "postgres:postgres" not in text
            assert "postgresql://" not in text.lower()

    def test_env_examples_document_backup_keys(self):
        root_env = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        cfg = (REPO_ROOT / "backend/properties/config.env.example").read_text(
            encoding="utf-8"
        )
        for text in (root_env, cfg):
            assert "BACKUP_DIR=" in text
            assert "BACKUP_RETENTION_DAYS=" in text
            assert "BACKUP_ENCRYPT=" in text
