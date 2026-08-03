"""Centralized Telegram beta access control for bot handlers."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from backend.src.app.services.telegram_command_authorization import (
    TelegramCommandPolicy,
    authorize_telegram_command_safe,
    command_policy,
)
from backend.src.app.telegram.messages import split_message

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


async def _reply_text(update: Update, text: str) -> None:
    message = update.effective_message
    if message is None:
        return
    for chunk in split_message(text):
        await message.reply_text(chunk)


def require_command_access(
    *,
    command_key: str,
    policy: TelegramCommandPolicy | None = None,
    denied_return: Any = None,
) -> Callable[[Handler], Handler]:
    """Authorize a Telegram command using centralized policy-based checks."""

    resolved_policy = policy or command_policy(command_key)

    def decorator(handler: Handler) -> Handler:
        @functools.wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
            user = update.effective_user
            if user is None:
                await _reply_text(update, "Utente Telegram non disponibile.")
                return denied_return

            result = authorize_telegram_command_safe(
                telegram_user_id=user.id,
                policy=resolved_policy,
                source="telegram",
                resource=getattr(handler, "__name__", "telegram_handler"),
                context={
                    "handler": getattr(handler, "__name__", "telegram_handler"),
                    "command_key": resolved_policy.command_key,
                },
            )
            if not result.allowed:
                await _reply_text(update, result.message or "Accesso non consentito.")
                return denied_return
            return await handler(update, context)

        return wrapper

    return decorator


def require_beta_access(
    *,
    entitlement_code: str | None = None,
    denied_message: str | None = None,
) -> Callable[[Handler], Handler]:
    """Backward-compatible alias for old premium-only decorator."""

    if not entitlement_code:
        raise ValueError("entitlement_code obbligatorio per require_beta_access")

    return require_command_access(
        command_key="legacy_beta",
        policy=TelegramCommandPolicy(
            command_key="legacy_beta",
            tier="premium",
            entitlement_code=entitlement_code,
            denied_message=denied_message,
        ),
    )

