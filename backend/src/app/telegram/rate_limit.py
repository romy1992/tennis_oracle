"""Telegram command rate limiting by telegram_user_id (DB-backed, multi-instance)."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from backend.src.app.core.config import get_settings
from backend.src.app.core.rate_limit import consume_rate_limit, get_rate_limit_session

logger = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]

RATE_LIMIT_MESSAGE = (
    "Stai inviando troppi comandi in poco tempo.\n"
    "Attendi circa {seconds} secondi e riprova."
)


def rate_limited(*, expensive: bool = False) -> Callable[[Handler], Handler]:
    """Reject excess commands per Telegram user with a clear Italian reply."""

    def decorator(handler: Handler) -> Handler:
        @functools.wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
            settings = get_settings()
            if not settings.rate_limit_enabled:
                return await handler(update, context)

            user = update.effective_user
            if user is None:
                return await handler(update, context)

            session = get_rate_limit_session()
            try:
                general = consume_rate_limit(
                    session,
                    bucket_key=f"telegram:user:{user.id}",
                    limit=settings.rate_limit_telegram,
                    window_seconds=settings.rate_limit_window_seconds,
                )
                if not general.allowed:
                    await _reply_limited(update, general.retry_after)
                    return None

                if expensive:
                    decision = consume_rate_limit(
                        session,
                        bucket_key=f"telegram:expensive:{user.id}",
                        limit=settings.rate_limit_telegram_expensive,
                        window_seconds=settings.rate_limit_window_seconds,
                    )
                    if not decision.allowed:
                        await _reply_limited(update, decision.retry_after)
                        return None
            except Exception:
                # Fail open on transient DB errors so the bot stays usable.
                logger.exception(
                    "Telegram rate-limit check failed user_id=%s; allowing request",
                    user.id,
                )
            finally:
                session.close()

            return await handler(update, context)

        return wrapper

    return decorator


async def _reply_limited(update: Update, retry_after: int) -> None:
    seconds = max(1, int(retry_after))
    text = RATE_LIMIT_MESSAGE.format(seconds=seconds)
    logger.warning(
        "Telegram rate limit hit user_id=%s retry_after=%s",
        update.effective_user.id if update.effective_user else None,
        seconds,
    )
    message = update.effective_message
    if message is not None:
        await message.reply_text(text)
        return
    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(text)
