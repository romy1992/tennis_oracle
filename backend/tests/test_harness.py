"""Smoke tests for the shared pytest harness (fixtures + isolation)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text


def test_health_via_client_fixture(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_db_session_is_sqlite(db_session):
    dialect = db_session.get_bind().dialect.name
    assert dialect == "sqlite"
    db_session.execute(text("SELECT 1"))


def test_auth_headers_fixture(client, auth_headers):
    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_import_state_path_is_temp(import_state_path: Path, tmp_path: Path):
    assert import_state_path.parent == tmp_path
    assert not import_state_path.exists()


def test_make_test_settings_forces_sqlite():
    from backend.tests.auth_helpers import make_test_settings

    settings = make_test_settings()
    assert settings.database_url.startswith("sqlite:")
    assert settings.admin_jwt_secret == "test-admin-jwt-secret-not-for-production"
