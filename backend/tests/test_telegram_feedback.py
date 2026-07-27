"""Tests for Telegram feedback service and admin API."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from backend.src.app.main import app
from backend.src.app.schemas.telegram_feedback import (
    TelegramFeedbackCreate,
    TelegramFeedbackStatusUpdate,
)
from backend.src.app.services.telegram_feedback import (
    TelegramFeedbackError,
    create_telegram_feedback,
    list_telegram_feedback,
    update_telegram_feedback_status,
)
from backend.src.app.telegram.bot import (
    FEEDBACK_CATEGORY,
    FEEDBACK_MESSAGE,
    FEEDBACK_RATING,
    FEEDBACK_USER_DATA_KEY,
    ConversationHandler,
    feedback_cancel,
    feedback_choose_category,
    feedback_choose_rating,
    feedback_receive_message,
    feedback_start,
)
from backend.src.entity.telegram_feedback import TelegramFeedback
from backend.tests.auth_helpers import (
    auth_header_for_admin,
    clear_settings_override,
    create_admin,
    make_test_settings,
    override_settings,
)
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client


class TelegramFeedbackServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.settings = make_test_settings()
        override_settings(self.settings)

    def tearDown(self):
        clear_settings_override()
        self.engine.dispose()

    def test_create_list_and_update_status(self):
        with self.Session() as session:
            created = create_telegram_feedback(
                session,
                TelegramFeedbackCreate(
                    telegram_user_id=42,
                    username="alice",
                    first_name="Alice",
                    category="bug",
                    rating=4,
                    message="Problema sulle schedine",
                ),
            )
            self.assertEqual(created.status, "new")
            self.assertEqual(created.category, "bug")
            self.assertEqual(created.rating, 4)
            self.assertEqual(created.telegram_user_id, 42)

            listed = list_telegram_feedback(session, status="new")
            self.assertEqual(listed.total, 1)
            self.assertEqual(listed.items[0].id, created.id)

            updated = update_telegram_feedback_status(
                session,
                created.id,
                TelegramFeedbackStatusUpdate(status="reviewing"),
            )
            self.assertEqual(updated.status, "reviewing")

            resolved = update_telegram_feedback_status(
                session,
                created.id,
                TelegramFeedbackStatusUpdate(status="resolved"),
            )
            self.assertEqual(resolved.status, "resolved")

            rejected = update_telegram_feedback_status(
                session,
                created.id,
                TelegramFeedbackStatusUpdate(status="rejected"),
            )
            self.assertEqual(rejected.status, "rejected")

            row = session.scalar(
                select(TelegramFeedback).where(TelegramFeedback.id == created.id)
            )
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row.status, "rejected")

    def test_invalid_category_and_status(self):
        with self.Session() as session:
            created = create_telegram_feedback(
                session,
                TelegramFeedbackCreate(
                    telegram_user_id=1,
                    category="ux",
                    rating=3,
                    message="ok",
                ),
            )
            with self.assertRaises(TelegramFeedbackError):
                list_telegram_feedback(session, status="unknown")
            with self.assertRaises(TelegramFeedbackError):
                list_telegram_feedback(session, category="unknown")
            with self.assertRaises(TelegramFeedbackError):
                update_telegram_feedback_status(
                    session,
                    created.id + 999,
                    TelegramFeedbackStatusUpdate(status="resolved"),
                )


class TelegramFeedbackApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.settings = make_test_settings()
        override_settings(self.settings)
        self.client = make_api_client(app, self.Session)
        with self.Session() as session:
            self.admin = create_admin(session, username="fb_admin")

    def tearDown(self):
        clear_settings_override()
        self.engine.dispose()

    def test_admin_list_and_patch_status(self):
        with self.Session() as session:
            created = create_telegram_feedback(
                session,
                TelegramFeedbackCreate(
                    telegram_user_id=99,
                    username="bob",
                    category="feature",
                    rating=5,
                    message="Vorrei un filtro torneo",
                ),
            )
            feedback_id = created.id

        headers = auth_header_for_admin(self.admin)
        listed = self.client.get("/api/telegram/feedback", headers=headers)
        self.assertEqual(listed.status_code, 200)
        body = listed.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["message"], "Vorrei un filtro torneo")

        patched = self.client.patch(
            f"/api/telegram/feedback/{feedback_id}",
            headers=headers,
            json={"status": "reviewing"},
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["status"], "reviewing")

        detail = self.client.get(
            f"/api/telegram/feedback/{feedback_id}",
            headers=headers,
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["status"], "reviewing")


class TelegramFeedbackBotHandlersTest(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_flow_saves_once(self):
        update = MagicMock()
        update.effective_user = MagicMock(
            id=42, username="alice", first_name="Alice", last_name=None
        )
        update.callback_query = None
        update.effective_message = MagicMock()
        update.effective_message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {}
        context.args = []

        with patch(
            "backend.src.app.telegram.bot._reply",
            new_callable=AsyncMock,
        ) as reply:
            state = await feedback_start(update, context)
            self.assertEqual(state, FEEDBACK_CATEGORY)
            self.assertIn(FEEDBACK_USER_DATA_KEY, context.user_data)

            update.callback_query = MagicMock(data="fb:cat:bug")
            update.callback_query.answer = AsyncMock()
            state = await feedback_choose_category(update, context)
            self.assertEqual(state, FEEDBACK_RATING)
            self.assertEqual(context.user_data[FEEDBACK_USER_DATA_KEY]["category"], "bug")

            update.callback_query = MagicMock(data="fb:rate:4")
            update.callback_query.answer = AsyncMock()
            state = await feedback_choose_rating(update, context)
            self.assertEqual(state, FEEDBACK_MESSAGE)
            self.assertEqual(context.user_data[FEEDBACK_USER_DATA_KEY]["rating"], 4)

            update.callback_query = None
            update.effective_message = MagicMock(text="Test messaggio feedback")
            update.effective_message.reply_text = AsyncMock()

            saved = MagicMock(id=11, category="bug", rating=4)
            with patch(
                "backend.src.app.telegram.bot.create_telegram_feedback_safe",
                return_value=saved,
            ) as create_safe:
                state = await feedback_receive_message(update, context)
                self.assertEqual(state, ConversationHandler.END)
                create_safe.assert_called_once()
                kwargs = create_safe.call_args.kwargs
                self.assertEqual(kwargs["category"], "bug")
                self.assertEqual(kwargs["rating"], 4)
                self.assertEqual(kwargs["message"], "Test messaggio feedback")
                self.assertNotIn(FEEDBACK_USER_DATA_KEY, context.user_data)
                self.assertTrue(reply.await_count >= 4)

    async def test_feedback_cancel_clears_draft(self):
        update = MagicMock()
        update.callback_query = None
        update.effective_message = MagicMock()
        context = MagicMock()
        context.user_data = {
            FEEDBACK_USER_DATA_KEY: {"category": "bug", "rating": 3}
        }
        with patch(
            "backend.src.app.telegram.bot._reply",
            new_callable=AsyncMock,
        ):
            state = await feedback_cancel(update, context)
        self.assertEqual(state, ConversationHandler.END)
        self.assertNotIn(FEEDBACK_USER_DATA_KEY, context.user_data)
