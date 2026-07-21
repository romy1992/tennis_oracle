"""Shared SQLite helpers for backend tests (path-agnostic, no real DB)."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.app.db.session import get_db
from backend.src.entity.base import Base

if TYPE_CHECKING:
    from backend.src.app.core.config import Settings


def _register_models() -> None:
    """Import ORM modules so ``Base.metadata`` is complete before ``create_all``."""
    import backend.src.app.models  # noqa: F401
    import backend.src.entity  # noqa: F401


def create_test_engine() -> Engine:
    """In-memory SQLite shared across connections (StaticPool)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _register_models()
    Base.metadata.create_all(bind=engine)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def install_get_db_override(
    app: FastAPI,
    session_factory: sessionmaker[Session],
) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db


def make_api_client(
    app: FastAPI,
    session_factory: sessionmaker[Session],
    *,
    settings: Settings | None = None,
) -> TestClient:
    """HTTP client with ``get_db`` override; rebinds ``SessionLocal`` for isolation.

    Lifespan is not entered unless the caller uses ``with client:``. Request handlers
    use the overridden ``get_db``. ``SessionLocal`` is pointed at the test engine so
    any accidental direct use (middleware helpers, etc.) stays on SQLite.
    """
    from backend.tests.auth_helpers import override_settings
    import backend.src.app.db.session as session_mod

    if settings is not None:
        override_settings(settings)
    install_get_db_override(app, session_factory)
    # Keep module-level SessionLocal on the isolated test DB (not real Postgres).
    session_mod.SessionLocal = session_factory
    bind = session_factory.kw.get("bind")
    if bind is not None:
        session_mod.engine = bind
    return TestClient(app)


def drop_all(engine: Engine) -> None:
    _register_models()
    Base.metadata.drop_all(bind=engine)
