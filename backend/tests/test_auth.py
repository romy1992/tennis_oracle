"""Tests for admin authentication and route protection."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.app.core.security import ALGORITHM, create_access_token
from backend.src.app.db.session import get_db
from backend.src.app.main import app
from backend.src.entity.admin_user import AdminUser
from backend.src.entity.base import Base
from backend.tests.auth_helpers import (
    TEST_JWT_SECRET,
    TEST_SERVICE_API_KEY,
    auth_header_for_admin,
    clear_settings_override,
    create_admin,
    make_test_settings,
    override_settings,
)


class AuthRoutesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.settings = make_test_settings(
            service_api_key=TEST_SERVICE_API_KEY,
            allow_unauthenticated_service_reads=False,
        )
        override_settings(self.settings)

        def override_get_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        with self.Session() as session:
            self.admin = create_admin(session, username="admin", password="correct-horse")

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_login_success_returns_access_token(self):
        response = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "correct-horse"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("access_token", payload)
        self.assertEqual(payload["token_type"], "bearer")
        self.assertIn("expires_at", payload)

    def test_login_rejects_wrong_password(self):
        response = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    def test_me_requires_auth(self):
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_me_with_valid_token(self):
        headers = auth_header_for_admin(self.admin, self.settings)
        response = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "admin")
        self.assertTrue(response.json()["authenticated"])

    def test_me_rejects_expired_token(self):
        expire = datetime.now(timezone.utc) - timedelta(minutes=1)
        token = jwt.encode(
            {
                "sub": "admin",
                "type": "access",
                "exp": expire,
                "iat": expire - timedelta(minutes=10),
                "admin_id": self.admin.id,
            },
            TEST_JWT_SECRET,
            algorithm=ALGORITHM,
        )
        response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 401)

    def test_disabled_admin_returns_403(self):
        with self.Session() as session:
            admin = session.get(AdminUser, self.admin.id)
            assert admin is not None
            admin.is_active = False
            session.commit()
            session.refresh(admin)
            headers = auth_header_for_admin(admin, self.settings)

        response = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_logout_requires_auth(self):
        response = self.client.post("/api/auth/logout")
        self.assertEqual(response.status_code, 401)

    def test_logout_ok_with_token(self):
        headers = auth_header_for_admin(self.admin, self.settings)
        response = self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])


class ProtectedRoutesAuthTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.settings = make_test_settings(
            service_api_key=TEST_SERVICE_API_KEY,
            allow_unauthenticated_service_reads=False,
        )
        override_settings(self.settings)

        def override_get_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        with self.Session() as session:
            self.admin = create_admin(session)
            self.headers = auth_header_for_admin(self.admin, self.settings)

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_telegram_events_unauthorized_without_token(self):
        response = self.client.get("/api/telegram/events")
        self.assertEqual(response.status_code, 401)

    def test_telegram_events_authorized_with_admin(self):
        response = self.client.get("/api/telegram/events", headers=self.headers)
        self.assertEqual(response.status_code, 200)

    def test_imports_status_unauthorized(self):
        response = self.client.get("/api/imports/status")
        self.assertEqual(response.status_code, 401)

    def test_imports_status_authorized(self):
        response = self.client.get("/api/imports/status", headers=self.headers)
        self.assertEqual(response.status_code, 200)

    def test_global_update_unauthorized(self):
        response = self.client.post("/api/global-update", json={})
        self.assertEqual(response.status_code, 401)

    @patch("backend.src.app.api.routes.global_update.start_global_update")
    def test_global_update_authorized(self, mock_start):
        mock_start.return_value = (None, "already running")
        with patch(
            "backend.src.app.api.routes.global_update.get_active_run",
            return_value=None,
        ):
            response = self.client.post(
                "/api/global-update",
                json={"force": True},
                headers=self.headers,
            )
        # 409 when no run returned and no active run
        self.assertIn(response.status_code, {200, 409})

    def test_service_token_allows_bot_read_endpoint(self):
        response = self.client.get(
            "/api/models-versions/results",
            headers={"X-Service-Token": TEST_SERVICE_API_KEY},
        )
        self.assertEqual(response.status_code, 200)

    def test_service_token_rejected_for_admin_endpoint(self):
        response = self.client.get(
            "/api/telegram/events",
            headers={"X-Service-Token": TEST_SERVICE_API_KEY},
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_service_token_rejected_on_bot_endpoint(self):
        response = self.client.get(
            "/api/next-fixtures",
            headers={"X-Service-Token": "wrong-key"},
        )
        self.assertEqual(response.status_code, 401)

    def test_betting_slips_regenerate_forbidden_with_service_token(self):
        response = self.client.get(
            "/api/betting-slips/daily",
            params={"regenerate": True},
            headers={"X-Service-Token": TEST_SERVICE_API_KEY},
        )
        self.assertEqual(response.status_code, 403)

    def test_password_is_hashed_not_plaintext(self):
        with self.Session() as session:
            admin = session.query(AdminUser).filter_by(username="admin").one()
            self.assertNotEqual(admin.password_hash, "secret-password")
            self.assertTrue(admin.password_hash.startswith("$2"))


class AuthHelpersUnitTest(unittest.TestCase):
    def test_create_access_token_roundtrip(self):
        settings = make_test_settings()
        token, expires_at = create_access_token(subject="alice", settings=settings)
        self.assertTrue(token)
        self.assertGreater(expires_at, datetime.now(timezone.utc))


if __name__ == "__main__":
    unittest.main()
