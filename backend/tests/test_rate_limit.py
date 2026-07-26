"""Tests for PostgreSQL-backed rate limiting (API middleware + Telegram)."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from backend.src.app.core.rate_limit import (
    consume_rate_limit,
    set_rate_limit_session_factory,
    window_start_utc,
)
from backend.src.app.main import app
from backend.src.app.telegram.rate_limit import rate_limited
from backend.src.entity.rate_limit_bucket import RateLimitBucket
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client
from backend.tests.auth_helpers import (
    clear_settings_override,
    make_test_settings,
    override_settings,
)


class RateLimitCoreTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_window_alignment(self):
        now = datetime(2026, 7, 21, 12, 0, 35, tzinfo=timezone.utc)
        ws = window_start_utc(now, 60)
        self.assertEqual(ws, datetime(2026, 7, 21, 12, 0, 0))

    def test_consume_allows_until_limit_then_blocks(self):
        with self.Session() as session:
            for _ in range(3):
                decision = consume_rate_limit(
                    session,
                    bucket_key="test:key",
                    limit=3,
                    window_seconds=60,
                )
                self.assertTrue(decision.allowed)
            blocked = consume_rate_limit(
                session,
                bucket_key="test:key",
                limit=3,
                window_seconds=60,
            )
            self.assertFalse(blocked.allowed)
            self.assertGreaterEqual(blocked.retry_after, 1)
            self.assertEqual(blocked.hit_count, 4)


class RateLimitMiddlewareTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        set_rate_limit_session_factory(self.Session)

        self.settings = make_test_settings(
            rate_limit_enabled=True,
            rate_limit_window_seconds=60,
            rate_limit_public=3,
            rate_limit_admin=100,
            rate_limit_internal=100,
            rate_limit_expensive=2,
            rate_limit_login=2,
            admin_jwt_secret="test-secret",
        )
        override_settings(self.settings)

        self.client = make_api_client(app, self.Session)

    def tearDown(self):
        set_rate_limit_session_factory(None)
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_health_is_excluded(self):
        for _ in range(10):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)

    def test_ready_is_excluded(self):
        for _ in range(10):
            response = self.client.get("/ready")
            self.assertIn(response.status_code, {200, 503})

    def test_public_ip_limit_returns_429_with_retry_after(self):
        for _ in range(3):
            response = self.client.get("/api/auth/me")
            self.assertIn(response.status_code, {401, 429})

        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)
        self.assertGreaterEqual(int(response.headers["Retry-After"]), 1)
        body = response.json()
        self.assertIn("detail", body)
        self.assertIn("retry_after", body)

    def test_login_has_stricter_limit(self):
        settings = make_test_settings(
            rate_limit_enabled=True,
            rate_limit_window_seconds=60,
            rate_limit_public=100,
            rate_limit_login=2,
            rate_limit_expensive=100,
            admin_jwt_secret="test-secret",
        )
        override_settings(settings)

        for _ in range(2):
            response = self.client.post(
                "/api/auth/login",
                json={"username": "nobody", "password": "wrong"},
            )
            self.assertIn(response.status_code, {401, 429, 503})

        response = self.client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)

    def test_service_token_uses_internal_bucket(self):
        settings = make_test_settings(
            rate_limit_enabled=True,
            rate_limit_window_seconds=60,
            rate_limit_public=1,
            rate_limit_internal=5,
            rate_limit_expensive=100,
            service_api_key="svc-test-key",
            allow_unauthenticated_service_reads=False,
        )
        override_settings(settings)

        headers = {"X-Service-Token": "svc-test-key"}
        for _ in range(3):
            response = self.client.get("/api/next-fixtures", headers=headers)
            self.assertNotEqual(response.status_code, 429)

    def test_disabled_rate_limit_allows_burst(self):
        override_settings(make_test_settings(rate_limit_enabled=False))
        for _ in range(20):
            response = self.client.get("/api/auth/me")
            self.assertEqual(response.status_code, 401)


class TelegramRateLimitTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        set_rate_limit_session_factory(self.Session)
        override_settings(
            make_test_settings(
                rate_limit_enabled=True,
                rate_limit_window_seconds=60,
                rate_limit_telegram=2,
                rate_limit_telegram_expensive=1,
            )
        )

    def tearDown(self):
        set_rate_limit_session_factory(None)
        clear_settings_override()
        self.engine.dispose()

    def test_telegram_user_limit_replies_in_italian(self):
        calls: list[str] = []

        @rate_limited()
        async def handler(update, context):
            calls.append("ok")

        async def run() -> None:
            for _ in range(2):
                update = MagicMock()
                update.effective_user = MagicMock(id=4242)
                update.effective_message = MagicMock()
                update.effective_message.reply_text = AsyncMock()
                update.callback_query = None
                await handler(update, MagicMock())

            update = MagicMock()
            update.effective_user = MagicMock(id=4242)
            update.effective_message = MagicMock()
            update.effective_message.reply_text = AsyncMock()
            update.callback_query = None
            await handler(update, MagicMock())

            self.assertEqual(calls, ["ok", "ok"])
            update.effective_message.reply_text.assert_awaited()
            text = update.effective_message.reply_text.await_args.args[0]
            self.assertIn("troppi comandi", text)
            self.assertIn("secondi", text)

        asyncio.run(run())

    def test_expensive_command_has_stricter_cap(self):
        calls: list[str] = []

        @rate_limited(expensive=True)
        async def handler(update, context):
            calls.append("ok")

        async def run() -> None:
            update = MagicMock()
            update.effective_user = MagicMock(id=99)
            update.effective_message = MagicMock()
            update.effective_message.reply_text = AsyncMock()
            update.callback_query = None
            await handler(update, MagicMock())

            update2 = MagicMock()
            update2.effective_user = MagicMock(id=99)
            update2.effective_message = MagicMock()
            update2.effective_message.reply_text = AsyncMock()
            update2.callback_query = None
            await handler(update2, MagicMock())

            self.assertEqual(calls, ["ok"])
            update2.effective_message.reply_text.assert_awaited()

        asyncio.run(run())


class RateLimitBucketEntityTest(unittest.TestCase):
    def test_entity_tablename(self):
        self.assertEqual(RateLimitBucket.__tablename__, "rate_limit_bucket")


if __name__ == "__main__":
    unittest.main()
