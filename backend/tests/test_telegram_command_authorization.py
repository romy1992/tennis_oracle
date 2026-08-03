"""Tests for centralized Telegram command authorization (free/premium)."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from backend.src.app.schemas.subscriptions import AccessDecision
from backend.src.app.schemas.telegram_users import TelegramUserAccessResult
from backend.src.app.services.telegram_command_authorization import (
    COMMAND_ABBONATI,
    COMMAND_FEEDBACK,
    COMMAND_GESTISCI_ABBONAMENTO,
    COMMAND_HELP,
    COMMAND_PARTITE,
    COMMAND_PIANO,
    TelegramAuthorizationResult,
    authorize_telegram_command_safe,
    command_policy,
)
from backend.src.app.telegram.access import require_command_access
from backend.tests.auth_helpers import (
    clear_settings_override,
    make_test_settings,
    override_settings,
)


def _decision(*, allowed: bool, reason: str | None, plan_code: str | None = None) -> AccessDecision:
    return AccessDecision(
        allowed=allowed,
        reason=reason,
        entitlement_code="telegram.command.partite",
        user_id=1,
        subscription_id=2,
        plan_code=plan_code,
        subscription_status="active",
        trial_ends_at=None,
        expires_at=None,
        checked_at=datetime(2026, 8, 1, 12, 0, 0),
    )


class TelegramCommandAuthorizationServiceTest(unittest.TestCase):
    def tearDown(self):
        clear_settings_override()

    def test_command_policy_classifies_free_and_premium(self):
        self.assertEqual(command_policy(COMMAND_HELP).tier, "free")
        self.assertEqual(command_policy(COMMAND_FEEDBACK).tier, "free")
        self.assertEqual(command_policy(COMMAND_PIANO).tier, "free")
        self.assertEqual(command_policy(COMMAND_ABBONATI).tier, "free")
        self.assertEqual(command_policy(COMMAND_GESTISCI_ABBONAMENTO).tier, "free")
        self.assertEqual(command_policy(COMMAND_PARTITE).tier, "premium")
        with self.assertRaises(ValueError):
            command_policy("unknown")

    def test_denied_telegram_gate_is_logged_via_forced_reason(self):
        gate = TelegramUserAccessResult(
            allowed=False,
            status="invited",
            reason="not_active",
            terms_required=False,
            terms_accepted=False,
            user=None,
        )
        with (
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_access_safe",
                return_value=gate,
            ),
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_entitlement_safe",
                return_value=_decision(allowed=False, reason="telegram_not_active", plan_code="free"),
            ) as entitlement_mock,
        ):
            result = authorize_telegram_command_safe(
                telegram_user_id=42,
                policy=command_policy(COMMAND_HELP),
                resource="help_command",
            )

        self.assertFalse(result.allowed)
        self.assertIn("lista di attesa", result.message or "")
        self.assertEqual(
            entitlement_mock.call_args.kwargs.get("forced_denial_reason"),
            "telegram_not_active",
        )

    def test_premium_denied_shows_upgrade_message(self):
        settings = make_test_settings(telegram_premium_upgrade_url="https://example.com/upgrade")
        override_settings(settings)

        with (
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_access_safe",
                return_value=TelegramUserAccessResult(
                    allowed=True,
                    status="active",
                    reason=None,
                    terms_required=False,
                    terms_accepted=True,
                    user=None,
                ),
            ),
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_entitlement_safe",
                return_value=_decision(allowed=False, reason="missing_entitlement", plan_code="free"),
            ),
        ):
            result = authorize_telegram_command_safe(
                telegram_user_id=77,
                policy=command_policy(COMMAND_PARTITE),
                resource="partite",
            )

        self.assertFalse(result.allowed)
        self.assertIn("piano premium", (result.message or "").lower())
        self.assertIn("https://example.com/upgrade", result.message or "")


class TelegramCommandAccessDecoratorTest(unittest.IsolatedAsyncioTestCase):
    async def test_decorator_stops_handler_on_denied(self):
        update = MagicMock()
        update.effective_user = MagicMock(id=500)
        update.effective_message = MagicMock()
        update.effective_message.reply_text = AsyncMock()
        context = MagicMock()

        handled = {"called": False}

        async def _handler(_update, _context):
            handled["called"] = True
            return "ok"

        guarded = require_command_access(command_key=COMMAND_PARTITE, denied_return="denied")(_handler)

        denied = TelegramAuthorizationResult(
            allowed=False,
            message="Upgrade richiesto",
            command_key=COMMAND_PARTITE,
            tier="premium",
            reason="missing_entitlement",
            plan_code="free",
            subscription_status="active",
            trial_ends_at=None,
            expires_at=None,
        )

        with patch(
            "backend.src.app.telegram.access.authorize_telegram_command_safe",
            return_value=denied,
        ):
            result = await guarded(update, context)

        self.assertEqual(result, "denied")
        self.assertFalse(handled["called"])
        update.effective_message.reply_text.assert_awaited_once_with("Upgrade richiesto")

    async def test_decorator_runs_handler_on_allowed(self):
        update = MagicMock()
        update.effective_user = MagicMock(id=700)
        update.effective_message = MagicMock()
        update.effective_message.reply_text = AsyncMock()
        context = MagicMock()

        async def _handler(_update, _context):
            return "ok"

        guarded = require_command_access(command_key=COMMAND_HELP)(_handler)

        allowed = TelegramAuthorizationResult(
            allowed=True,
            message=None,
            command_key=COMMAND_HELP,
            tier="free",
            reason=None,
            plan_code="free",
            subscription_status="active",
            trial_ends_at=None,
            expires_at=None,
        )

        with patch(
            "backend.src.app.telegram.access.authorize_telegram_command_safe",
            return_value=allowed,
        ):
            result = await guarded(update, context)

        self.assertEqual(result, "ok")
        update.effective_message.reply_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()



