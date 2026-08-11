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

    def test_denied_for_terms_required_shows_accept_instructions(self):
        """TELEGRAM_TERMS_REQUIRED=true, utente attivo ma non ha ancora accettato:
        /partite (premium) deve bloccarsi con le istruzioni per /accetta_condizioni,
        PRIMA ancora di valutare l'entitlement del piano."""
        gate = TelegramUserAccessResult(
            allowed=False,
            status="active",
            reason="terms_required",
            terms_required=True,
            terms_accepted=False,
            user=None,
        )
        with (
            patch(
                "backend.src.app.services.telegram_command_authorization.is_feature_enabled_safe",
                return_value=True,
            ),
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_access_safe",
                return_value=gate,
            ),
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_entitlement_safe",
                return_value=_decision(allowed=True, reason=None, plan_code="pro"),
            ) as entitlement_mock,
        ):
            result = authorize_telegram_command_safe(
                telegram_user_id=99,
                policy=command_policy(COMMAND_PARTITE),
                resource="partite",
            )

        self.assertFalse(result.allowed)
        self.assertIn("condizioni d'uso", (result.message or "").lower())
        self.assertIn("/accetta_condizioni", result.message or "")
        self.assertEqual(
            entitlement_mock.call_args.kwargs.get("forced_denial_reason"),
            "telegram_terms_required",
        )

    def test_premium_denied_shows_upgrade_message(self):
        settings = make_test_settings(telegram_premium_upgrade_url="https://example.com/upgrade")
        override_settings(settings)

        with (
            patch(
                "backend.src.app.services.telegram_command_authorization.is_feature_enabled_safe",
                return_value=True,
            ),
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

    def test_subscription_commands_are_disabled_by_feature_flag(self):
        with (
            patch(
                "backend.src.app.services.telegram_command_authorization.is_feature_enabled_safe",
                return_value=False,
            ),
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_access_safe"
            ) as gate_mock,
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_entitlement_safe"
            ) as entitlement_mock,
        ):
            result = authorize_telegram_command_safe(
                telegram_user_id=77,
                policy=command_policy(COMMAND_ABBONATI),
                resource="abbonati",
            )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "feature_disabled")
        self.assertEqual(result.message, "Comando non disponibile al momento.")
        gate_mock.assert_not_called()
        entitlement_mock.assert_not_called()

    def test_premium_command_feature_check_is_fail_closed(self):
        policy = command_policy(COMMAND_PARTITE)
        calls: list[tuple[str, bool]] = []

        def _feature_enabled(*, key: str, default_enabled: bool = True) -> bool:
            calls.append((key, default_enabled))
            if key == "telegram.authorizations_enabled":
                return True
            return False

        with (
            patch(
                "backend.src.app.services.telegram_command_authorization.is_feature_enabled_safe",
                side_effect=_feature_enabled,
            ),
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_access_safe"
            ) as gate_mock,
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_entitlement_safe"
            ) as entitlement_mock,
        ):
            result = authorize_telegram_command_safe(
                telegram_user_id=77,
                policy=policy,
                resource="partite",
            )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "feature_disabled")
        self.assertEqual(result.message, "Comando non disponibile al momento.")
        self.assertIn((policy.feature_flag_key or "", False), calls)
        gate_mock.assert_not_called()
        entitlement_mock.assert_not_called()

    def test_premium_command_unlocks_when_subscriptions_disabled(self):
        """Piano abbonamenti OFF -> /partite, /schedine, /statistiche si sbloccano."""

        def _feature_enabled(*, key: str, default_enabled: bool = True) -> bool:
            if key == "telegram.subscriptions_enabled":
                return False
            return True

        with (
            patch(
                "backend.src.app.services.telegram_command_authorization.is_feature_enabled_safe",
                side_effect=_feature_enabled,
            ),
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

        self.assertTrue(result.allowed)
        self.assertIsNone(result.message)
        self.assertEqual(result.reason, "subscriptions_disabled_bypass")

    def test_premium_bypass_does_not_hide_real_entitlement_errors(self):
        """Il bypass da subscriptions OFF non deve nascondere errori tecnici reali."""

        def _feature_enabled(*, key: str, default_enabled: bool = True) -> bool:
            if key == "telegram.subscriptions_enabled":
                return False
            return True

        with (
            patch(
                "backend.src.app.services.telegram_command_authorization.is_feature_enabled_safe",
                side_effect=_feature_enabled,
            ),
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
                return_value=_decision(allowed=False, reason="entitlement_check_error", plan_code=None),
            ),
        ):
            result = authorize_telegram_command_safe(
                telegram_user_id=77,
                policy=command_policy(COMMAND_PARTITE),
                resource="partite",
            )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "entitlement_check_error")

    def test_free_command_is_unaffected_by_premium_bypass(self):
        """/piano resta legato al proprio feature flag (subscriptions), non al bypass premium."""

        def _feature_enabled(*, key: str, default_enabled: bool = True) -> bool:
            if key == "telegram.subscriptions_enabled":
                return False
            return True

        with (
            patch(
                "backend.src.app.services.telegram_command_authorization.is_feature_enabled_safe",
                side_effect=_feature_enabled,
            ),
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_access_safe"
            ) as gate_mock,
            patch(
                "backend.src.app.services.telegram_command_authorization.check_telegram_entitlement_safe"
            ) as entitlement_mock,
        ):
            result = authorize_telegram_command_safe(
                telegram_user_id=77,
                policy=command_policy(COMMAND_PIANO),
                resource="piano",
            )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "feature_disabled")
        gate_mock.assert_not_called()
        entitlement_mock.assert_not_called()


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

    async def test_partite_blocked_before_terms_accepted_then_unlocked_after(self):
        """Simula esattamente il flusso richiesto: /partite (decoratore reale usato
        da bot.py) blocca l'handler finche' le condizioni non sono accettate, poi lo
        esegue normalmente subito dopo /accetta_condizioni — senza restart, stesso
        processo, stessa richiesta successiva."""
        update = MagicMock()
        update.effective_user = MagicMock(id=900)
        update.effective_message = MagicMock()
        update.effective_message.reply_text = AsyncMock()
        context = MagicMock()

        handled = {"count": 0}

        async def _partite_handler(_update, _context):
            handled["count"] += 1
            return "partite-content"

        guarded = require_command_access(command_key=COMMAND_PARTITE, denied_return="denied")(
            _partite_handler
        )

        denied_for_terms = TelegramAuthorizationResult(
            allowed=False,
            message=(
                "Devi accettare le condizioni d'uso prima di continuare.\n"
                "Invia /accetta_condizioni per confermare."
            ),
            command_key=COMMAND_PARTITE,
            tier="premium",
            reason="terms_required",
            plan_code="pro",
            subscription_status="active",
            trial_ends_at=None,
            expires_at=None,
        )

        # 1) Prima di /accetta_condizioni: bloccato, handler MAI chiamato.
        with patch(
            "backend.src.app.telegram.access.authorize_telegram_command_safe",
            return_value=denied_for_terms,
        ):
            result_before = await guarded(update, context)

        self.assertEqual(result_before, "denied")
        self.assertEqual(handled["count"], 0)
        update.effective_message.reply_text.assert_awaited_once_with(denied_for_terms.message)

        # 2) Dopo /accetta_condizioni: consentito, handler eseguito e contenuto restituito.
        allowed_after = TelegramAuthorizationResult(
            allowed=True,
            message=None,
            command_key=COMMAND_PARTITE,
            tier="premium",
            reason=None,
            plan_code="pro",
            subscription_status="active",
            trial_ends_at=None,
            expires_at=None,
        )
        with patch(
            "backend.src.app.telegram.access.authorize_telegram_command_safe",
            return_value=allowed_after,
        ):
            result_after = await guarded(update, context)

        self.assertEqual(result_after, "partite-content")
        self.assertEqual(handled["count"], 1)


if __name__ == "__main__":
    unittest.main()










