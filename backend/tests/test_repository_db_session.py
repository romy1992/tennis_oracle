"""Guard: repository layer must share app.db.session (no second engine)."""

from __future__ import annotations

import backend.src.app.db.session as app_session
import backend.src.repository.base.repository_db as repository_db


def test_repository_db_reexports_app_session_factory() -> None:
    assert repository_db.SessionLocal is app_session.SessionLocal
    assert repository_db.engine is app_session.engine


def test_make_api_client_rebinds_repository_db_session(
    db_session_factory,
    test_settings,
) -> None:
    from backend.src.app.main import app
    from backend.tests.db_helpers import make_api_client

    make_api_client(app, db_session_factory, settings=test_settings)
    try:
        assert app_session.SessionLocal is db_session_factory
        assert repository_db.SessionLocal is db_session_factory
        bind = db_session_factory.kw.get("bind")
        if bind is not None:
            assert app_session.engine is bind
            assert repository_db.engine is bind
    finally:
        app.dependency_overrides.clear()
