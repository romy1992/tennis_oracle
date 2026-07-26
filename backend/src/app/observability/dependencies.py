"""Dependency status for readiness / ops dashboards (DB, Telegram, trackers)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings
from backend.src.app.observability.errors import error_tracking_provider
from backend.src.app.observability.metrics import metrics_provider


def check_database(db: Session) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}


def build_dependencies_status(
    settings: Settings,
    *,
    db: Session | None = None,
    database_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured dependency health (never includes secrets)."""
    db_info = database_status
    if db_info is None and db is not None:
        db_info = check_database(db)
    if db_info is None:
        db_info = {"status": "unknown"}

    telegram_token = bool((getattr(settings, "telegram_bot_token", None) or "").strip())
    admin_chat = bool((getattr(settings, "telegram_admin_chat_id", None) or "").strip())
    alerts_enabled = bool(getattr(settings, "ops_alerts_enabled", False))

    deps: dict[str, Any] = {
        "database": db_info,
        "error_tracking": {
            "provider": error_tracking_provider(),
            "status": "ok" if error_tracking_provider() != "none" else "disabled",
        },
        "metrics": {
            "provider": metrics_provider(),
            "status": "ok" if metrics_provider() != "none" else "disabled",
        },
        "telegram_alerts": {
            "enabled": alerts_enabled,
            "bot_token_configured": telegram_token,
            "admin_chat_configured": admin_chat,
            "status": (
                "ok"
                if alerts_enabled and telegram_token and admin_chat
                else ("partial" if alerts_enabled else "disabled")
            ),
        },
        "alert_webhook": {
            "configured": bool((getattr(settings, "ops_alert_webhook_url", None) or "").strip()),
            "status": (
                "ok"
                if (getattr(settings, "ops_alert_webhook_url", None) or "").strip()
                else "disabled"
            ),
        },
    }

    critical_ok = db_info.get("status") == "ok"
    return {
        "status": "ok" if critical_ok else "degraded",
        "environment": settings.app_env,
        "dependencies": deps,
    }
