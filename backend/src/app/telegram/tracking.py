from __future__ import annotations

import functools
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

# `python -m src.app.telegram.bot` is launched from backend/; ensure repo root is
# importable so `backend.src.*` packages resolve (same as Alembic/FastAPI).
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.src.app.services.telegram_analytics import record_telegram_event_safe

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


def _command_action(update: Update, fallback: str) -> str:
    message = update.effective_message
    text = message.text if message and message.text else None
    if text and text.startswith("/"):
        token = text.split()[0]
        # Strip @BotName from /command@BotName
        return token.split("@", 1)[0].lower()
    return fallback


def tracked(
    *,
    action: str | None = None,
    event_type: str = "command",
) -> Callable[[Handler], Handler]:
    """Wrap a Telegram handler to persist analytics without breaking replies."""

    def decorator(handler: Handler) -> Handler:
        @functools.wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
            message = update.effective_message
            text = message.text if message and message.text else None
            if action:
                resolved_action = action
            elif event_type == "callback" and update.callback_query and update.callback_query.data:
                resolved_action = update.callback_query.data[:255]
            elif event_type == "message":
                if text and text.startswith("/"):
                    resolved_action = _command_action(update, "unknown")
                else:
                    resolved_action = "(message)"
            else:
                resolved_action = _command_action(update, "unknown")

            success = True
            error_message: str | None = None
            try:
                return await handler(update, context)
            except Exception as exc:
                success = False
                error_message = str(exc)
                raise
            finally:
                user = update.effective_user
                chat = update.effective_chat
                raw_text = None
                if event_type == "callback" and update.callback_query:
                    raw_text = update.callback_query.data
                elif text:
                    raw_text = text
                record_telegram_event_safe(
                    event_type=event_type,
                    action=resolved_action,
                    telegram_user_id=user.id if user else None,
                    chat_id=chat.id if chat else None,
                    username=user.username if user else None,
                    first_name=user.first_name if user else None,
                    last_name=user.last_name if user else None,
                    raw_text=raw_text,
                    success=success,
                    error_message=error_message,
                )

        return wrapper

    return decorator


async def track_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record inline-button clicks; ready for future keyboards."""
    query = update.callback_query
    if query is None:
        return
    try:
        await query.answer()
    except Exception:
        pass
    user = update.effective_user
    chat = update.effective_chat
    data = query.data or "callback"
    record_telegram_event_safe(
        event_type="callback",
        action=data[:255],
        telegram_user_id=user.id if user else None,
        chat_id=chat.id if chat else None,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        last_name=user.last_name if user else None,
        raw_text=data,
        success=True,
    )
