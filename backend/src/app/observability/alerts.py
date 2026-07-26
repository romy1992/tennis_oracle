"""Administrative alerts (Telegram + optional webhook). Fail-open by design."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from backend.src.app.observability.context import get_correlation_id
from backend.src.utility.sensitive_data import sanitize_text

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_LAST_SENT: dict[str, float] = {}


def _should_send(dedupe_key: str | None, cooldown_seconds: int) -> bool:
    if not dedupe_key or cooldown_seconds <= 0:
        return True
    now = time.time()
    with _LOCK:
        last = _LAST_SENT.get(dedupe_key)
        if last is not None and (now - last) < cooldown_seconds:
            return False
        _LAST_SENT[dedupe_key] = now
        return True


def send_admin_alert(
    message: str,
    *,
    severity: str = "warning",
    dedupe_key: str | None = None,
    telegram_bot_token: str | None = None,
    telegram_admin_chat_id: str | None = None,
    webhook_url: str | None = None,
    cooldown_seconds: int = 300,
    enabled: bool = True,
) -> dict[str, Any]:
    """Send an admin alert via configured channels. Never raises to callers."""
    result: dict[str, Any] = {
        "sent": False,
        "skipped": False,
        "telegram": "disabled",
        "webhook": "disabled",
    }
    if not enabled:
        result["skipped"] = True
        result["reason"] = "alerts_disabled"
        return result
    if not _should_send(dedupe_key, cooldown_seconds):
        result["skipped"] = True
        result["reason"] = "cooldown"
        return result

    cid = get_correlation_id() or "-"
    body = (
        f"[tennis_oracle][{severity.upper()}]\n"
        f"{sanitize_text(message, max_length=3500)}\n"
        f"correlation_id={cid}"
    )

    token = (telegram_bot_token or "").strip()
    chat_id = (telegram_admin_chat_id or "").strip()
    if token and chat_id:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            response = httpx.post(
                url,
                json={"chat_id": chat_id, "text": body, "disable_web_page_preview": True},
                timeout=8.0,
            )
            if response.is_success:
                result["telegram"] = "ok"
                result["sent"] = True
            else:
                result["telegram"] = f"http_{response.status_code}"
                logger.warning(
                    "Telegram admin alert failed status=%s",
                    response.status_code,
                )
        except Exception:
            result["telegram"] = "error"
            logger.warning("Telegram admin alert exception", exc_info=True)
    elif chat_id and not token:
        result["telegram"] = "missing_token"
    elif token and not chat_id:
        result["telegram"] = "missing_chat_id"

    hook = (webhook_url or "").strip()
    if hook:
        try:
            response = httpx.post(
                hook,
                json={
                    "severity": severity,
                    "message": sanitize_text(message, max_length=3500),
                    "correlation_id": cid,
                    "source": "tennis_oracle",
                },
                timeout=8.0,
            )
            if response.is_success:
                result["webhook"] = "ok"
                result["sent"] = True
            else:
                result["webhook"] = f"http_{response.status_code}"
        except Exception:
            result["webhook"] = "error"
            logger.warning("Alert webhook exception", exc_info=True)

    if not result["sent"] and result.get("reason") is None:
        # No channel configured — log so ops still see it.
        logger.warning("admin_alert_unrouted severity=%s message=%s", severity, sanitize_text(message))
        result["reason"] = "no_channel"
    return result
