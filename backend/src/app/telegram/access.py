"""Centralized Telegram beta access control for bot handlers."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from backend.src.app.services.telegram_users import (
    access_denial_message,
    check_telegram_access_safe,
)
from backend.src.app.telegram.messages import split_message

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


async def _reply_text(update: Update, text: str) -> None:
    message = update.effective_message
    if message is None:
        return
    for chunk in split_message(text):
        await message.reply_text(chunk)


def require_beta_access() -> Callable[[Handler], Handler]:
    """Deny privileged commands unless the user passes whitelist + terms checks."""

    def decorator(handler: Handler) -> Handler:
        @functools.wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
            user = update.effective_user
            if user is None:
                await _reply_text(update, "Utente Telegram non disponibile.")
                return None
            result = check_telegram_access_safe(telegram_user_id=user.id)
            if not result.allowed:
                await _reply_text(update, access_denial_message(result))
                return None
            return await handler(update, context)

        return wrapper

    return decorator
