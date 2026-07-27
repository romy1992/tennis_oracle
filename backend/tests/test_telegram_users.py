"""Tests for Telegram beta user registry, whitelist and admin API."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from backend.src.app.main import app
from backend.src.app.schemas.telegram_users import TelegramUserInviteCreate
from backend.src.app.services.telegram_users import (
    accept_telegram_terms,
    activate_telegram_user,
    block_telegram_user,
    check_telegram_access,
    invite_telegram_user,
    list_telegram_users,
    register_or_touch_on_start,
    suspend_telegram_user,
)
from backend.src.entity.telegram_user import TelegramUser
from backend.tests.auth_helpers import (
    auth_header_for_admin,
    clear_settings_override,
    create_admin,
    make_test_settings,
    override_settings,
)
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client


class TelegramUsersServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.settings = make_test_settings(
            telegram_whitelist_enabled=True,
            telegram_terms_required=False,
            telegram_terms_version="1",
        )
        override_settings(self.settings)

    def tearDown(self):
        clear_settings_override()
        self.engine.dispose()

    def test_register_on_start_creates_invited_when_whitelist_on(self):
        with self.Session() as session:
            user = register_or_touch_on_start(
                session,
                telegram_user_id=42,
                username="alice",
                first_name="Alice",
                last_name="Rossi",
                invite_origin="beta_wave1",
                settings=self.settings,
            )
            self.assertEqual(user.telegram_user_id, 42)
            self.assertEqual(user.username, "alice")
            self.assertEqual(user.first_name, "Alice")
            self.assertEqual(user.status, "invited")
            self.assertEqual(user.invite_origin, "beta_wave1")
            self.assertFalse(user.terms_accepted)

            again = register_or_touch_on_start(
                session,
                telegram_user_id=42,
                username="alice2",
                first_name="Alice",
                invite_origin="ignored_second",
                settings=self.settings,
            )
            self.assertEqual(again.username, "alice2")
            self.assertEqual(again.invite_origin, "beta_wave1")
            self.assertEqual(again.status, "invited")
            stored = session.scalar(
                select(TelegramUser).where(TelegramUser.telegram_user_id == 42)
            )
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertGreaterEqual(stored.last_access_at, stored.first_access_at)

    def test_register_on_start_auto_active_when_whitelist_off(self):
        open_settings = make_test_settings(telegram_whitelist_enabled=False)
        with self.Session() as session:
            user = register_or_touch_on_start(
                session,
                telegram_user_id=7,
                username="bob",
                settings=open_settings,
            )
            self.assertEqual(user.status, "active")

    def test_access_denied_until_activated_and_terms(self):
        terms_settings = make_test_settings(
            telegram_whitelist_enabled=True,
            telegram_terms_required=True,
            telegram_terms_version="2",
        )
        with self.Session() as session:
            register_or_touch_on_start(
                session,
                telegram_user_id=99,
                username="carol",
                settings=terms_settings,
            )
            denied = check_telegram_access(
                session,
                telegram_user_id=99,
                settings=terms_settings,
                touch_last_access=False,
            )
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.reason, "not_active")

            activate_telegram_user(session, 99)
            still_terms = check_telegram_access(
                session,
                telegram_user_id=99,
                settings=terms_settings,
                touch_last_access=False,
            )
            self.assertFalse(still_terms.allowed)
            self.assertEqual(still_terms.reason, "terms_required")

            accept_telegram_terms(session, telegram_user_id=99, settings=terms_settings)
            allowed = check_telegram_access(
                session,
                telegram_user_id=99,
                settings=terms_settings,
                touch_last_access=False,
            )
            self.assertTrue(allowed.allowed)
            self.assertEqual(allowed.user.terms_version if allowed.user else None, "2")

    def test_suspend_and_block(self):
        with self.Session() as session:
            register_or_touch_on_start(
                session,
                telegram_user_id=11,
                settings=self.settings,
            )
            activate_telegram_user(session, 11)
            suspend_telegram_user(session, 11)
            suspended = check_telegram_access(
                session,
                telegram_user_id=11,
                settings=self.settings,
                touch_last_access=False,
            )
            self.assertEqual(suspended.reason, "suspended")
            block_telegram_user(session, 11)
            blocked = check_telegram_access(
                session,
                telegram_user_id=11,
                settings=self.settings,
                touch_last_access=False,
            )
            self.assertEqual(blocked.reason, "blocked")

    def test_list_search_and_invite(self):
        with self.Session() as session:
            invite_telegram_user(
                session,
                TelegramUserInviteCreate(
                    telegram_user_id=1001,
                    username="preuser",
                    invite_origin="admin_invite",
                    status="invited",
                ),
            )
            register_or_touch_on_start(
                session,
                telegram_user_id=1002,
                username="other",
                first_name="Other",
                settings=self.settings,
            )
            activate_telegram_user(session, 1002)
            found = list_telegram_users(session, q="preuser")
            self.assertEqual(found.total, 1)
            self.assertEqual(found.items[0].telegram_user_id, 1001)
            active = list_telegram_users(session, status="active")
            self.assertEqual(active.total, 1)
            self.assertEqual(active.items[0].telegram_user_id, 1002)


class TelegramUsersApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.settings = make_test_settings(
            telegram_whitelist_enabled=True,
            telegram_terms_required=False,
        )
        with self.Session() as session:
            self.admin = create_admin(session)
        self.client = make_api_client(app, self.Session, settings=self.settings)
        self.headers = auth_header_for_admin(self.admin, self.settings)

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_admin_search_activate_suspend_block(self):
        create = self.client.post(
            "/api/telegram/users",
            headers=self.headers,
            json={
                "telegram_user_id": 555,
                "username": "beta_user",
                "invite_origin": "wave1",
            },
        )
        self.assertEqual(create.status_code, 201, create.text)
        self.assertEqual(create.json()["status"], "invited")

        search = self.client.get(
            "/api/telegram/users",
            headers=self.headers,
            params={"q": "beta_user"},
        )
        self.assertEqual(search.status_code, 200)
        payload = search.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["telegram_user_id"], 555)

        activated = self.client.post(
            "/api/telegram/users/555/activate",
            headers=self.headers,
        )
        self.assertEqual(activated.status_code, 200)
        self.assertEqual(activated.json()["status"], "active")

        suspended = self.client.post(
            "/api/telegram/users/555/suspend",
            headers=self.headers,
        )
        self.assertEqual(suspended.status_code, 200)
        self.assertEqual(suspended.json()["status"], "suspended")

        blocked = self.client.post(
            "/api/telegram/users/555/block",
            headers=self.headers,
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertEqual(blocked.json()["status"], "blocked")

    def test_unauthenticated_rejected(self):
        response = self.client.get("/api/telegram/users")
        self.assertEqual(response.status_code, 401)


class TelegramStartRegistrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_registers_user_and_mentions_status(self):
        from backend.src.app.telegram import bot as bot_module

        update = MagicMock()
        update.effective_user.id = 4242
        update.effective_user.username = "starter"
        update.effective_user.first_name = "Start"
        update.effective_user.last_name = "Er"
        update.message = AsyncMock()
        context = MagicMock()
        context.args = ["invite_from_link"]
        context.application.bot_data = {
            "settings": MagicMock(
                telegram_whitelist_enabled=True,
                telegram_terms_required=False,
                telegram_feedback_url=None,
            )
        }

        with (
            patch(
                "backend.src.app.telegram.bot.register_or_touch_on_start_safe",
                return_value=MagicMock(
                    status="invited",
                    invite_origin="invite_from_link",
                    terms_accepted=False,
                ),
            ) as register_mock,
            patch("backend.src.app.telegram.bot._reply", new_callable=AsyncMock) as reply_mock,
        ):
            await bot_module.start(update, context)

        register_mock.assert_called_once()
        kwargs = register_mock.call_args.kwargs
        self.assertEqual(kwargs["telegram_user_id"], 4242)
        self.assertEqual(kwargs["invite_origin"], "invite_from_link")
        reply_mock.assert_awaited()
        text = reply_mock.await_args.args[1]
        self.assertIn("In lista di attesa", text)
        self.assertIn("invite_from_link", text)
        self.assertNotIn("logistic_regression", text)
        self.assertIsNotNone(reply_mock.await_args.kwargs.get("reply_markup"))


if __name__ == "__main__":
    unittest.main()
