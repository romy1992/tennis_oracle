"""Pytest fixtures and process-wide isolation for the backend suite.

Import order matters: environment variables are set before any application
modules that read DATABASE_URL / API keys at import time.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# Process-wide isolation (must run before importing app.db.session / request_api)
# ---------------------------------------------------------------------------
_TEST_ENV = {
    "DATABASE_URL": "sqlite://",
    "DATABASE_SOURCE_URL": "sqlite://",
    "DATABASE_TARGET_URL": "sqlite://",
    "API_TENNIS_KEY": "test-api-tennis-key-not-real",
    "API_TENNIS_BASE": "https://example.test/tennis/",
    "RUNTIME_SECRETS_MASTER_KEY": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_SERVICE_API_KEY": "",
    "SERVICE_API_KEY": "",
    "SERVICE_API_KEY_PREVIOUS": "",
    "ADMIN_JWT_SECRET": "test-admin-jwt-secret-not-for-production",
    "ADMIN_USERNAME": "",
    "ADMIN_PASSWORD": "",
    "SYNC_CLOUD": "false",
    "RATE_LIMIT_ENABLED": "false",
    "GLOBAL_UPDATE_CRON_ENABLED": "false",
}

for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value

from backend.src.app.core.config import set_settings_override
from backend.tests.auth_helpers import (
    auth_header_for_admin,
    clear_settings_override,
    create_admin,
    make_test_settings,
    override_settings,
)
from backend.tests.db_helpers import (
    create_session_factory,
    create_test_engine,
    make_api_client,
)

set_settings_override(make_test_settings(rate_limit_enabled=False))


def pytest_configure(config: pytest.Config) -> None:
    """Re-assert isolation after pytest startup."""
    for key, value in _TEST_ENV.items():
        os.environ[key] = value
    set_settings_override(make_test_settings(rate_limit_enabled=False))


@pytest.fixture
def test_settings() -> Generator[Any, None, None]:
    settings = make_test_settings(rate_limit_enabled=False)
    override_settings(settings)
    try:
        yield settings
    finally:
        clear_settings_override()


@pytest.fixture
def db_engine() -> Generator[Engine, None, None]:
    engine = create_test_engine()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session_factory(db_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(db_engine)


@pytest.fixture
def db_session(db_session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """DB session; rolls back uncommitted work after each test."""
    session = db_session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(
    db_session_factory: sessionmaker[Session],
    test_settings: Any,
) -> Generator[TestClient, None, None]:
    from backend.src.app.main import app

    api = make_api_client(app, db_session_factory, settings=test_settings)
    try:
        yield api
    finally:
        app.dependency_overrides.clear()
        clear_settings_override()


@pytest.fixture
def auth_headers(db_session: Session, test_settings: Any) -> dict[str, str]:
    admin = create_admin(db_session)
    return auth_header_for_admin(admin, test_settings)


@pytest.fixture
def import_state_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect import_state.json to a temp file (no repo data mutation)."""
    path = tmp_path / "import_state.json"
    monkeypatch.setattr(
        "backend.src.app.services.import_state.STATE_PATH",
        path,
    )
    return path


@pytest.fixture(autouse=True)
def _isolate_import_state(import_state_path: Path) -> Path:
    """Always isolate import_state.json for every test."""
    return import_state_path


@pytest.fixture(autouse=True)
def _block_external_api_tennis(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Block real API-Tennis HTTP unless the test module exercises the client."""
    if "test_request_api" in request.node.nodeid:
        yield
        return

    def _blocked(*_args: Any, **_kwargs: Any) -> None:
        from backend.src.utility.request_api import ApiTennisNetworkError

        raise ApiTennisNetworkError(
            "External API-Tennis HTTP blocked in tests; mock request_api or use fixtures."
        )

    with patch("backend.src.utility.request_api.requests.get", side_effect=_blocked), patch(
        "backend.src.utility.request_api.requests.post", side_effect=_blocked
    ):
        yield
