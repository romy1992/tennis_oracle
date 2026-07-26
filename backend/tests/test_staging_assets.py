"""Regression checks for staging packaging assets (no Docker daemon required)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class TestStagingAssetsExist:
    def test_required_files_present(self):
        required = [
            "docker-compose.staging.yml",
            ".env.staging.example",
            "docs/STAGING.md",
            "backend/scripts/run_alembic_upgrade.py",
            "backend/scripts/smoke_check.py",
            "frontend/nginx.https.conf.example",
        ]
        missing = [p for p in required if not (REPO_ROOT / p).is_file()]
        assert missing == [], f"Missing staging assets: {missing}"


class TestComposeStaging:
    @pytest.fixture(scope="class")
    def compose_text(self) -> str:
        return _read("docker-compose.staging.yml")

    def test_isolated_project_and_volume(self, compose_text: str):
        assert "name: tennis_oracle_staging" in compose_text
        assert "postgres_data_staging" in compose_text
        assert "tennis_oracle_staging_postgres_data" in compose_text
        assert "tennis_db_staging" in compose_text

    def test_db_always_on_separate_ports(self, compose_text: str):
        assert "profiles: !reset" in compose_text
        assert "STAGING_POSTGRES_PORT" in compose_text
        assert "STAGING_API_PORT" in compose_text
        assert "STAGING_FRONTEND_PORT" in compose_text

    def test_controlled_migrations(self, compose_text: str):
        assert "AUTO_MIGRATE" in compose_text
        assert "run_alembic_upgrade.py" in compose_text
        assert "condition: service_healthy" in compose_text

    def test_cors_and_ready_healthcheck(self, compose_text: str):
        assert "CORS_ORIGINS" in compose_text
        assert "CORS_ORIGIN_REGEX" in compose_text
        assert "/ready" in compose_text
        assert "APP_ENV" in compose_text

    def test_bot_uses_staging_env(self, compose_text: str):
        assert ".env.staging" in compose_text
        assert "TELEGRAM_API_BASE_URL" in compose_text
        assert "TELEGRAM_SERVICE_API_KEY" in compose_text


class TestEnvStagingExample:
    def test_documented_keys_no_real_secrets(self):
        text = _read(".env.staging.example")
        for key in (
            "APP_ENV=staging",
            "AUTO_MIGRATE=",
            "tennis_db_staging",
            "STAGING_API_PORT=",
            "CORS_ORIGINS=",
            "TELEGRAM_BOT_TOKEN=",
            "VITE_API_BASE_URL=",
            "change-me",
        ):
            assert key in text
        assert "sk_live" not in text.lower()
        assert "ghp_" not in text
        assert "AAF1H3" not in text


class TestRunAlembicUpgradeScript:
    def test_skips_when_auto_migrate_false(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AUTO_MIGRATE", "false")
        script = REPO_ROOT / "backend" / "scripts" / "run_alembic_upgrade.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(REPO_ROOT / "backend"),
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "AUTO_MIGRATE": "false"},
        )
        assert result.returncode == 0
        assert "skipping" in result.stdout.lower()


class TestSmokeCheckScript:
    def test_help_lists_ready(self):
        script = REPO_ROOT / "backend" / "scripts" / "smoke_check.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "--base-url" in result.stdout
        assert "--expect-env" in result.stdout
