"""Tests for the beta terms premise text (BETA_TERMS_TEXT), mostrato prima/durante
/accetta_condizioni cosi' l'utente non "accetta al buio" senza aver letto nulla sulla
fase beta, l'assenza di garanzie e il rischio di perdita.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.src.app.telegram.messages import BETA_TERMS_TEXT


class BetaTermsTextContentTest(unittest.TestCase):
    def test_mentions_beta_phase_risk_and_no_guarantee(self):
        self.assertIn("BETA", BETA_TERMS_TEXT)
        self.assertIn("Tennis Oracle", BETA_TERMS_TEXT)
        self.assertNotIn("tennis_oracle", BETA_TERMS_TEXT)
        self.assertIn("rischio", BETA_TERMS_TEXT.lower())
        self.assertIn("non garantiscono", BETA_TERMS_TEXT.lower())
        self.assertIn("perdere", BETA_TERMS_TEXT.lower())


class StartShowsBetaTermsWhenPendingTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_always_includes_beta_terms_text_regardless_of_terms_flag(self):
        """BETA_TERMS_TEXT e' nel welcome standard (build_welcome_text): deve comparire
        SEMPRE su /start, anche con TELEGRAM_TERMS_REQUIRED=false (configurazione reale
        di default del progetto) e anche se le condizioni sono gia' state accettate."""
        from backend.src.app.telegram import bot as bot_module

        update = MagicMock()
        update.effective_user.id = 5001
        update.effective_user.username = "pending"
        update.effective_user.first_name = "Pending"
        update.effective_user.last_name = "User"
        update.message = AsyncMock()
        context = MagicMock()
        context.args = []
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
                return_value=MagicMock(status="active", invite_origin=None, terms_accepted=True),
            ),
            patch(
                "backend.src.app.telegram.bot._telegram_feature_flags",
                return_value={"telegram.authorizations_enabled": False},
            ),
            patch("backend.src.app.telegram.bot._reply", new_callable=AsyncMock) as reply_mock,
        ):
            await bot_module.start(update, context)

        reply_mock.assert_awaited()
        text = reply_mock.await_args.args[1]
        self.assertIn(BETA_TERMS_TEXT, text)

    async def test_start_includes_beta_terms_text_when_terms_not_yet_accepted(self):
        from backend.src.app.telegram import bot as bot_module

        update = MagicMock()
        update.effective_user.id = 5002
        update.effective_user.username = "accepted"
        update.effective_user.first_name = "Accepted"
        update.effective_user.last_name = "User"
        update.message = AsyncMock()
        context = MagicMock()
        context.args = []
        context.application.bot_data = {
            "settings": MagicMock(
                telegram_whitelist_enabled=True,
                telegram_terms_required=True,
                telegram_feedback_url=None,
            )
        }

        with (
            patch(
                "backend.src.app.telegram.bot.register_or_touch_on_start_safe",
                return_value=MagicMock(status="active", invite_origin=None, terms_accepted=False),
            ),
            patch(
                "backend.src.app.telegram.bot._telegram_feature_flags",
                return_value={"telegram.authorizations_enabled": True},
            ),
            patch("backend.src.app.telegram.bot._reply", new_callable=AsyncMock) as reply_mock,
        ):
            await bot_module.start(update, context)

        reply_mock.assert_awaited()
        text = reply_mock.await_args.args[1]
        self.assertIn(BETA_TERMS_TEXT, text)
        self.assertIn("/accetta_condizioni", text)


class AccettaCondizioniShowsBetaTermsTest(unittest.IsolatedAsyncioTestCase):
    async def test_accetta_condizioni_includes_beta_terms_text_in_confirmation(self):
        from backend.src.app.telegram import bot as bot_module

        update = MagicMock()
        update.effective_user.id = 6001
        context = MagicMock()
        context.application.bot_data = {"settings": MagicMock(telegram_terms_required=True)}

        with (
            patch(
                "backend.src.app.telegram.bot.accept_telegram_terms_safe",
                return_value=MagicMock(terms_version="1", status="active"),
            ) as accept_mock,
            patch("backend.src.app.telegram.bot._reply", new_callable=AsyncMock) as reply_mock,
        ):
            await bot_module.accetta_condizioni(update, context)

        accept_mock.assert_called_once_with(telegram_user_id=6001)
        reply_mock.assert_awaited()
        text = reply_mock.await_args.args[1]
        self.assertIn(BETA_TERMS_TEXT, text)
        self.assertIn("Condizioni accettate (versione 1)", text)

    async def test_accetta_condizioni_shows_beta_text_even_when_flag_disabled(self):
        """Configurazione reale di default (TELEGRAM_TERMS_REQUIRED=false): il comando
        risponde subito senza passare da accept_telegram_terms_safe, ma deve comunque
        mostrare la premessa beta, non solo 'non richiesta'."""
        from backend.src.app.telegram import bot as bot_module

        update = MagicMock()
        update.effective_user.id = 6002
        context = MagicMock()
        context.application.bot_data = {"settings": MagicMock(telegram_terms_required=False)}

        with patch("backend.src.app.telegram.bot._reply", new_callable=AsyncMock) as reply_mock:
            await bot_module.accetta_condizioni(update, context)

        reply_mock.assert_awaited()
        text = reply_mock.await_args.args[1]
        self.assertIn(BETA_TERMS_TEXT, text)


if __name__ == "__main__":
    unittest.main()




