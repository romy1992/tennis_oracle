"""Tests for outbound Telegram notifications (dedupe, prefs, delivery)."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock

import httpx
from sqlalchemy import select

from backend.src.app.schemas.telegram_users import TelegramNotificationPreferencesUpdate
from backend.src.app.services.telegram_notifications import (
    KIND_EMPTY_DAY,
    KIND_PREDICTIONS,
    KIND_RESULTS,
    STATUS_FAILED,
    STATUS_SENT,
    STATUS_SKIPPED,
    deliver_to_user,
    list_notification_recipients,
    make_dedupe_key,
    run_notification_kind,
)
from backend.src.app.services.telegram_users import (
    activate_telegram_user,
    register_or_touch_on_start,
    suspend_telegram_user,
    update_notification_preferences,
)
from backend.src.app.telegram.messages import (
    format_notification_predictions,
    format_notification_preferences,
    format_notification_results,
)
from backend.src.entity.telegram_notification_delivery import TelegramNotificationDelivery
from backend.src.entity.telegram_user import TelegramUser
from backend.tests.auth_helpers import (
    clear_settings_override,
    make_test_settings,
    override_settings,
)
from backend.tests.db_helpers import create_session_factory, create_test_engine


def _ok_response(message_id: int = 1001) -> MagicMock:
    response = MagicMock()
    response.is_success = True
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = {"ok": True, "result": {"message_id": message_id}}
    response.headers = {}
    return response


def _http_error(status_code: int, *, retry_after: float | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.telegram.org/botTOKEN/sendMessage")
    headers = {}
    payload = {"ok": False, "description": f"err_{status_code}"}
    if retry_after is not None:
        payload["parameters"] = {"retry_after": retry_after}
        headers["Retry-After"] = str(retry_after)
    response = httpx.Response(status_code, json=payload, request=request, headers=headers)
    return httpx.HTTPStatusError("boom", request=request, response=response)


class TelegramNotificationsServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.settings = make_test_settings(
            telegram_whitelist_enabled=True,
            telegram_terms_required=False,
            telegram_bot_token="test-token",
            telegram_notifications_enabled=True,
            telegram_notify_predictions_enabled=True,
            telegram_notify_results_enabled=True,
            telegram_notify_empty_day_enabled=True,
            telegram_notify_min_interval_seconds=0.0,
            telegram_notify_max_retries=1,
            telegram_notify_retry_backoff_seconds=0.0,
            public_model_version="v3",
            public_model_name="logistic_regression",
        )
        override_settings(self.settings)

    def tearDown(self):
        clear_settings_override()
        self.engine.dispose()

    def _seed_active_user(
        self,
        *,
        telegram_user_id: int = 42,
        chat_id: int | None = 42,
        notify_predictions: bool = True,
        notify_results: bool = True,
        notify_empty_day: bool = True,
        notifications_enabled: bool = True,
    ) -> TelegramUser:
        with self.Session() as session:
            register_or_touch_on_start(
                session,
                telegram_user_id=telegram_user_id,
                username=f"u{telegram_user_id}",
                chat_id=chat_id,
                settings=self.settings,
            )
            activate_telegram_user(session, telegram_user_id)
            update_notification_preferences(
                session,
                telegram_user_id=telegram_user_id,
                payload=TelegramNotificationPreferencesUpdate(
                    notifications_enabled=notifications_enabled,
                    notify_predictions=notify_predictions,
                    notify_results=notify_results,
                    notify_empty_day=notify_empty_day,
                ),
            )
            row = session.scalar(
                select(TelegramUser).where(TelegramUser.telegram_user_id == telegram_user_id)
            )
            assert row is not None
            session.expunge(row)
            return row

    def test_list_recipients_skips_suspended_and_prefs_off(self):
        self._seed_active_user(telegram_user_id=1, chat_id=1)
        self._seed_active_user(
            telegram_user_id=2,
            chat_id=2,
            notify_predictions=False,
        )
        self._seed_active_user(telegram_user_id=3, chat_id=3)
        with self.Session() as session:
            suspend_telegram_user(session, 3)
            recipients = list_notification_recipients(
                session, kind=KIND_PREDICTIONS, settings=self.settings
            )
        ids = {u.telegram_user_id for u in recipients}
        self.assertEqual(ids, {1})

    def test_list_recipients_requires_chat_id(self):
        self._seed_active_user(telegram_user_id=7, chat_id=None)
        with self.Session() as session:
            recipients = list_notification_recipients(
                session, kind=KIND_PREDICTIONS, settings=self.settings
            )
        self.assertEqual(recipients, [])

    def test_deliver_dedupe_and_retry(self):
        user = self._seed_active_user()
        sleeps: list[float] = []
        calls = {"n": 0}

        def http_post(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_error(429, retry_after=0.01)
            return _ok_response(55)

        with self.Session() as session:
            row = session.scalar(
                select(TelegramUser).where(TelegramUser.telegram_user_id == user.telegram_user_id)
            )
            assert row is not None
            first = deliver_to_user(
                session,
                user=row,
                kind=KIND_PREDICTIONS,
                content_date=date(2026, 7, 27),
                message="ciao",
                bot_token="token",
                max_retries=1,
                retry_backoff_seconds=0.0,
                sleep_fn=sleeps.append,
                http_post=http_post,
            )
            self.assertEqual(first.status, STATUS_SENT)
            self.assertEqual(first.telegram_message_id, 55)
            self.assertEqual(calls["n"], 2)
            self.assertTrue(sleeps)

            second = deliver_to_user(
                session,
                user=row,
                kind=KIND_PREDICTIONS,
                content_date=date(2026, 7, 27),
                message="ciao",
                bot_token="token",
                max_retries=1,
                retry_backoff_seconds=0.0,
                sleep_fn=sleeps.append,
                http_post=http_post,
            )
            self.assertEqual(second.status, STATUS_SKIPPED)
            self.assertEqual(second.skipped_reason, "already_sent")
            self.assertEqual(calls["n"], 2)

            deliveries = list(session.scalars(select(TelegramNotificationDelivery)).all())
            self.assertEqual(len(deliveries), 1)
            self.assertEqual(deliveries[0].status, STATUS_SENT)
            self.assertEqual(
                deliveries[0].dedupe_key,
                make_dedupe_key(KIND_PREDICTIONS, date(2026, 7, 27), 42),
            )

    def test_deliver_permanent_failure_no_retry_loop(self):
        user = self._seed_active_user(telegram_user_id=99, chat_id=99)
        calls = {"n": 0}

        def http_post(*_args, **_kwargs):
            calls["n"] += 1
            raise _http_error(403)

        with self.Session() as session:
            row = session.scalar(
                select(TelegramUser).where(TelegramUser.telegram_user_id == 99)
            )
            assert row is not None
            result = deliver_to_user(
                session,
                user=row,
                kind=KIND_RESULTS,
                content_date=date(2026, 7, 26),
                message="riepilogo",
                bot_token="token",
                max_retries=3,
                retry_backoff_seconds=0.0,
                sleep_fn=lambda _s: None,
                http_post=http_post,
            )
            self.assertEqual(result.status, STATUS_FAILED)
            self.assertEqual(calls["n"], 1)

    def test_run_kind_disabled_globally(self):
        disabled = make_test_settings(
            telegram_notifications_enabled=False,
            telegram_bot_token="token",
        )
        with self.Session() as session:
            summary = run_notification_kind(
                session,
                kind=KIND_EMPTY_DAY,
                content_date=date(2026, 7, 27),
                settings=disabled,
                dry_run=True,
            )
        self.assertEqual(summary.message_preview, "notifications_disabled")
        self.assertEqual(summary.recipients, 0)

    def test_message_formatters(self):
        preds = format_notification_predictions(
            [
                {
                    "event_first_player": "A",
                    "event_second_player": "B",
                    "event_time": "10:30:00",
                    "prediction": {"predicted_winner": "A"},
                }
            ],
            "2026-07-27",
        )
        self.assertIn("Pronostici del giorno", preds)
        self.assertIn("A vs B", preds)

        results = format_notification_results(
            "2026-07-26",
            {
                "predictions_total": 4,
                "predictions_resolved": 3,
                "predictions_correct": 2,
                "predictions_lost": 1,
                "pending": 1,
                "accuracy_pct": 66.7,
                "theoretical_profit_units": 1.2,
                "theoretical_roi_pct": 12.0,
            },
        )
        self.assertIn("Riepilogo risultati", results)
        self.assertIn("66.7%", results)

        with self.Session() as session:
            user = register_or_touch_on_start(
                session,
                telegram_user_id=11,
                chat_id=11,
                settings=self.settings,
            )
        prefs = format_notification_preferences(user)
        self.assertIn("Preferenze notifiche", prefs)
        self.assertIn("Master:", prefs)


class TelegramNotificationsMessagesExtrasTest(unittest.TestCase):
    def test_empty_results_formatter(self):
        text = format_notification_results("2026-07-26", None)
        self.assertIn("Nessun dato disponibile", text)


if __name__ == "__main__":
    unittest.main()
