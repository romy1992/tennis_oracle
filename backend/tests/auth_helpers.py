"""Shared helpers for authenticated API tests."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.core.security import hash_password
from backend.src.app.services.auth import issue_access_token
from backend.src.entity.admin_user import AdminUser


TEST_JWT_SECRET = "test-admin-jwt-secret-not-for-production"
TEST_SERVICE_API_KEY = "test-service-api-key"


def make_test_settings(**overrides) -> Settings:
    base = {
        "admin_jwt_secret": TEST_JWT_SECRET,
        "admin_jwt_expire_minutes": 60,
        "service_api_key": None,
        "allow_unauthenticated_service_reads": True,
        "admin_username": None,
        "admin_password": None,
    }
    base.update(overrides)
    return Settings(**base)


def override_settings(settings: Settings) -> None:
    get_settings.cache_clear()

    def _get() -> Settings:
        return settings

    from backend.src.app.main import app

    app.dependency_overrides[get_settings] = _get


def clear_settings_override() -> None:
    from backend.src.app.main import app

    app.dependency_overrides.pop(get_settings, None)
    get_settings.cache_clear()


def create_admin(
    session: Session,
    *,
    username: str = "admin",
    password: str = "secret-password",
    is_active: bool = True,
) -> AdminUser:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    admin = AdminUser(
        username=username,
        password_hash=hash_password(password),
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    return admin


def auth_header_for_admin(admin: AdminUser, settings: Settings | None = None) -> dict[str, str]:
    cfg = settings or make_test_settings()
    token, _ = issue_access_token(admin, cfg)
    return {"Authorization": f"Bearer {token}"}


def authed_client_headers(client: TestClient, session: Session, settings: Settings) -> dict[str, str]:
    admin = create_admin(session)
    return auth_header_for_admin(admin, settings)
