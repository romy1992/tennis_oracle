"""Tests for protected API-Tennis runtime settings."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from sqlalchemy import select

from backend.src.app.api.routes import settings as settings_routes
from backend.src.app.services.runtime_secrets import (
    API_TENNIS_SECRET_KEY,
    resolve_api_tennis_key_from_db,
)
from backend.src.entity.admin_audit_log import AdminAuditLog
from backend.src.entity.runtime_secret import RuntimeSecret
from backend.src.utility import request_api as request_api_module
from backend.tests.auth_helpers import make_test_settings, override_settings

NEW_API_KEY = "new-api-tennis-key-not-real"
LEGACY_MASTER_KEY = Fernet.generate_key().decode("ascii")


def _provider_settings():
    return make_test_settings(
        app_env="test",
        api_tennis_key="environment-api-tennis-key-not-real",
        api_tennis_base="https://example.test/tennis/",
        api_tennis_timeout=12.0,
    )


def test_api_tennis_settings_require_admin(client):
    assert client.get("/api/settings/providers/api-tennis").status_code == 401
    assert (
        client.post("/api/settings/providers/api-tennis/test", json={}).status_code
        == 401
    )
    assert (
        client.patch(
            "/api/settings/providers/api-tennis/key",
            json={
                "api_key": NEW_API_KEY,
                "admin_password": "secret-password",
            },
        ).status_code
        == 401
    )


def test_settings_status_never_returns_environment_key(client, auth_headers):
    response = client.get(
        "/api/settings/providers/api-tennis",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "environment"
    assert payload["configured"] is True
    assert payload["usable"] is True
    assert payload["storage_ready"] is True
    assert payload["fingerprint"].startswith("sha256:")
    assert "test-api-tennis-key-not-real" not in response.text


def test_admin_can_verify_save_and_activate_database_key(
    client,
    auth_headers,
    db_session,
):
    settings = _provider_settings()
    override_settings(settings)

    with patch.object(settings_routes, "request_api", return_value=[]) as provider_call:
        response = client.patch(
            "/api/settings/providers/api-tennis/key",
            headers=auth_headers,
            json={
                "api_key": NEW_API_KEY,
                "admin_password": "secret-password",
                "verify_before_save": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["settings"]["source"] == "database"
    assert payload["settings"]["usable"] is True
    assert NEW_API_KEY not in response.text
    provider_call.assert_called_once_with(
        method="get_events",
        api_key_override=NEW_API_KEY,
    )

    db_session.expire_all()
    row = db_session.get(RuntimeSecret, API_TENNIS_SECRET_KEY)
    assert row is not None
    assert row.encryption_scheme == "database-v1"
    assert row.encrypted_value == NEW_API_KEY
    assert (
        resolve_api_tennis_key_from_db(
            db_session,
            settings=settings,
        )
        == NEW_API_KEY
    )

    audit = db_session.scalar(
        select(AdminAuditLog)
        .where(AdminAuditLog.action == "provider_secret_update")
        .order_by(AdminAuditLog.id.desc())
    )
    assert audit is not None
    assert NEW_API_KEY not in (audit.context_json or "")
    assert '"verified_before_save": true' in (audit.context_json or "")

    provider_response = MagicMock()
    provider_response.status_code = 200
    provider_response.url = "https://example.test/tennis/"
    provider_response.json.return_value = {"result": []}
    with patch.object(
        request_api_module.requests, "get", return_value=provider_response
    ) as get:
        request_api_module.request_api(method="get_events")
    assert get.call_args.kwargs["params"]["APIkey"] == NEW_API_KEY


def test_failed_verification_does_not_replace_key(
    client,
    auth_headers,
    db_session,
):
    settings = _provider_settings()
    override_settings(settings)

    with patch.object(
        settings_routes,
        "request_api",
        side_effect=request_api_module.ApiTennisHttpError("API Tennis HTTP 401"),
    ):
        response = client.patch(
            "/api/settings/providers/api-tennis/key",
            headers=auth_headers,
            json={
                "api_key": NEW_API_KEY,
                "admin_password": "secret-password",
                "verify_before_save": True,
            },
        )

    assert response.status_code == 422
    assert "Chiave non salvata" in response.json()["detail"]
    assert db_session.get(RuntimeSecret, API_TENNIS_SECRET_KEY) is None


def test_admin_can_force_save_without_provider_verification(
    client,
    auth_headers,
    db_session,
):
    settings = _provider_settings()
    override_settings(settings)

    with patch.object(settings_routes, "request_api") as provider_call:
        response = client.patch(
            "/api/settings/providers/api-tennis/key",
            headers=auth_headers,
            json={
                "api_key": NEW_API_KEY,
                "admin_password": "secret-password",
                "verify_before_save": False,
            },
        )

    assert response.status_code == 200
    assert response.json()["verified"] is False
    provider_call.assert_not_called()
    assert db_session.get(RuntimeSecret, API_TENNIS_SECRET_KEY) is not None


def test_existing_fernet_value_remains_readable(db_session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(
        RuntimeSecret(
            key=API_TENNIS_SECRET_KEY,
            encrypted_value=Fernet(LEGACY_MASTER_KEY.encode("ascii"))
            .encrypt(NEW_API_KEY.encode("utf-8"))
            .decode("ascii"),
            encryption_scheme="fernet-v1",
            fingerprint="sha256:legacy",
            created_at=now,
            updated_at=now,
            updated_by="admin",
        )
    )
    db_session.commit()

    settings = make_test_settings(runtime_secrets_master_key=LEGACY_MASTER_KEY)
    assert resolve_api_tennis_key_from_db(db_session, settings=settings) == NEW_API_KEY


def test_update_requires_current_admin_password_but_no_extra_master_key(
    client,
    auth_headers,
    db_session,
):
    override_settings(_provider_settings())
    wrong_password = client.patch(
        "/api/settings/providers/api-tennis/key",
        headers=auth_headers,
        json={
            "api_key": NEW_API_KEY,
            "admin_password": "wrong-password",
            "verify_before_save": False,
        },
    )
    assert wrong_password.status_code == 403

    override_settings(
        make_test_settings(
            api_tennis_key="environment-api-tennis-key-not-real",
            runtime_secrets_master_key=None,
        )
    )
    no_master_key = client.patch(
        "/api/settings/providers/api-tennis/key",
        headers=auth_headers,
        json={
            "api_key": NEW_API_KEY,
            "admin_password": "secret-password",
            "verify_before_save": False,
        },
    )
    assert no_master_key.status_code == 200
    row = db_session.get(RuntimeSecret, API_TENNIS_SECRET_KEY)
    assert row is not None
    assert row.encryption_scheme == "database-v1"
