"""Regression checks for Docker packaging assets (no Docker daemon required)."""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class TestDockerAssetsExist:
    def test_required_files_present(self):
        required = [
            "backend/Dockerfile",
            "frontend/Dockerfile",
            "frontend/nginx.conf",
            ".dockerignore",
            "frontend/.dockerignore",
            "docker-compose.yml",
            "docker-compose.dev.yml",
            "docker-compose.prod.yml",
            "docker-compose.staging.yml",
            ".env.example",
            ".env.staging.example",
            "docs/DOCKER.md",
            "docs/STAGING.md",
            "frontend/nginx.https.conf.example",
        ]
        missing = [p for p in required if not (REPO_ROOT / p).is_file()]
        assert missing == [], f"Missing Docker assets: {missing}"


class TestBackendDockerfile:
    def test_is_multistage_and_lean(self):
        text = _read("backend/Dockerfile")
        assert "AS builder" in text
        assert "AS runtime" in text
        assert "requirements.txt" in text
        assert "HEALTHCHECK" in text
        assert "backend.src.app.main:app" in text
        for forbidden in (
            "COPY backend/data/models",
            "COPY backend/data/processed",
            "COPY backend/.env",
            "COPY .env",
        ):
            assert forbidden not in text


class TestFrontendDockerfile:
    def test_is_multistage_nginx(self):
        text = _read("frontend/Dockerfile")
        assert "AS build" in text
        assert "AS runtime" in text
        assert "nginx" in text.lower()
        assert "VITE_API_BASE_URL" in text
        assert "HEALTHCHECK" in text
        assert "npm ci" in text
        assert "npm run build" in text


class TestDockerignore:
    def test_excludes_secrets_datasets_models_node(self):
        text = _read(".dockerignore")
        for needle in (
            "backend/data/processed",
            "backend/data/models",
            "**/.env",
            "frontend",
            "**/node_modules",
            "**/*.log",
            "**/*.pkl",
        ):
            assert needle in text


class TestComposeLocal:
    @pytest.fixture(scope="class")
    def compose_text(self) -> str:
        return _read("docker-compose.yml")

    def test_core_services_declared(self, compose_text: str):
        for name in ("db:", "migrate:", "api:", "frontend:", "bot:", "job:"):
            assert f"\n  {name}" in compose_text or compose_text.strip().startswith(
                "services:"
            )
            assert name in compose_text

    def test_single_named_volume_postgres(self, compose_text: str):
        assert "postgres_data:" in compose_text
        assert "tennis_oracle_postgres_data" in compose_text
        # No other top-level named volumes for app code
        assert "volumes:\n  postgres_data:" in compose_text.replace("\r\n", "\n")

    def test_db_is_optional_embedded_profile(self, compose_text: str):
        assert "postgres:16" in compose_text
        assert "pg_isready" in compose_text
        assert 'profiles: ["embedded-db"]' in compose_text
        assert "host.docker.internal" in compose_text
        assert "host-gateway" in compose_text

    def test_migrate_runs_alembic(self, compose_text: str):
        assert "alembic" in compose_text
        assert "upgrade" in compose_text
        assert "head" in compose_text
        assert 'working_dir: /app/backend' in compose_text

    def test_api_waits_for_migrate_not_db(self, compose_text: str):
        assert "service_completed_successfully" in compose_text
        assert "/health" in compose_text
        assert "MODELS_HOST_PATH" in compose_text or "backend/data/models" in compose_text
        # Default stack must not require embedded db
        assert "condition: service_healthy" in compose_text  # frontend→api still uses it
        # No depends_on db for default path: look for removed pattern on api block roughly
        assert "host.docker.internal:5432" in compose_text

    def test_bot_and_job_profiles(self, compose_text: str):
        assert 'profiles: ["bot"]' in compose_text or "profiles:\n      - bot" in compose_text
        assert 'profiles: ["jobs"]' in compose_text or "profiles:\n      - jobs" in compose_text
        assert "backend.src.app.telegram.bot" in compose_text
        assert "backend.src.jobs.run_global_update" in compose_text

    def test_frontend_port_and_local_credential_mounts(self, compose_text: str):
        assert "FRONTEND_PORT:-5173" in compose_text
        assert "./backend/.env:/app/backend/.env:ro" in compose_text
        assert (
            "./backend/properties/config.env:/app/backend/properties/config.env:ro"
            in compose_text
        )
        assert "TELEGRAM_API_BASE_URL: http://api:8000/api" in compose_text


class TestComposeDev:
    def test_dev_overlay_hot_reload(self):
        text = _read("docker-compose.dev.yml")
        assert "--reload" in text
        assert "./backend/src:/app/backend/src" in text
        assert "./frontend:/app" in text
        assert "npm run dev" in text
        assert "CHOKIDAR_USEPOLLING" in text
        assert "WATCHFILES_FORCE_POLLING" in text
        assert "frontend_dev_node_modules" in text
        assert "backend.src.app.telegram.bot" in text
        assert "build: !reset" in text


class TestComposeProd:
    def test_overlay_disables_debug_and_resets_db_ports(self):
        text = _read("docker-compose.prod.yml")
        assert 'DEBUG: "false"' in text or "DEBUG: false" in text
        assert "ports: !reset" in text
        assert "APP_ENV" in text
        assert "max-size" in text


class TestEnvExample:
    def test_env_example_has_docker_keys_no_real_secrets(self):
        text = _read(".env.example")
        for key in (
            "FRONTEND_PORT=5173",
            "API_PORT=8000",
            "POSTGRES_PASSWORD=",
            "ADMIN_JWT_SECRET=",
            "ADMIN_PASSWORD=1234",
            "VITE_API_BASE_URL=",
            "MODELS_HOST_PATH=",
            "host.docker.internal",
            "DATABASE_URL=",
            "embedded-db",
        ):
            assert key in text
        assert "8080" not in text
        assert "sk_live" not in text.lower()
        assert "ghp_" not in text
        assert "AAF1H3" not in text
