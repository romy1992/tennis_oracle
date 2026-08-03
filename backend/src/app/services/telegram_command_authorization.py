"""Centralized authorization service for Telegram command access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from backend.src.app.core.config import get_settings
from backend.src.app.schemas.subscriptions import AccessDecision
from backend.src.app.services.subscriptions import (
    TELEGRAM_ENTITLEMENT_FREE,
    TELEGRAM_ENTITLEMENT_PARTITE,
    TELEGRAM_ENTITLEMENT_SCHEDINE,
    TELEGRAM_ENTITLEMENT_STATISTICHE,
    check_telegram_entitlement_safe,
)
from backend.src.app.services.telegram_users import (
    access_denial_message,
    check_telegram_access_safe,
)

CommandTier = Literal["free", "premium"]

COMMAND_HELP = "help"
COMMAND_FEEDBACK = "feedback"
COMMAND_NOTIFICHE = "notifiche"
COMMAND_PARTITE = "partite"
COMMAND_SCHEDINE = "schedine"
COMMAND_STATISTICHE = "statistiche"
COMMAND_PIANO = "piano"
COMMAND_ABBONATI = "abbonati"
COMMAND_GESTISCI_ABBONAMENTO = "gestisci_abbonamento"


@dataclass(frozen=True)
class TelegramCommandPolicy:
    command_key: str
    tier: CommandTier
    entitlement_code: str
    denied_message: str | None = None


@dataclass(frozen=True)
class TelegramAuthorizationResult:
    allowed: bool
    message: str | None
    command_key: str
    tier: CommandTier
    reason: str | None
    plan_code: str | None
    subscription_status: str | None
    trial_ends_at: datetime | None
    expires_at: datetime | None


_TELEGRAM_COMMAND_POLICIES: dict[str, TelegramCommandPolicy] = {
    COMMAND_HELP: TelegramCommandPolicy(
        command_key=COMMAND_HELP,
        tier="free",
        entitlement_code=TELEGRAM_ENTITLEMENT_FREE,
    ),
    COMMAND_FEEDBACK: TelegramCommandPolicy(
        command_key=COMMAND_FEEDBACK,
        tier="free",
        entitlement_code=TELEGRAM_ENTITLEMENT_FREE,
    ),
    COMMAND_NOTIFICHE: TelegramCommandPolicy(
        command_key=COMMAND_NOTIFICHE,
        tier="free",
        entitlement_code=TELEGRAM_ENTITLEMENT_FREE,
    ),
    COMMAND_PIANO: TelegramCommandPolicy(
        command_key=COMMAND_PIANO,
        tier="free",
        entitlement_code=TELEGRAM_ENTITLEMENT_FREE,
    ),
    COMMAND_ABBONATI: TelegramCommandPolicy(
        command_key=COMMAND_ABBONATI,
        tier="free",
        entitlement_code=TELEGRAM_ENTITLEMENT_FREE,
    ),
    COMMAND_GESTISCI_ABBONAMENTO: TelegramCommandPolicy(
        command_key=COMMAND_GESTISCI_ABBONAMENTO,
        tier="free",
        entitlement_code=TELEGRAM_ENTITLEMENT_FREE,
    ),
    COMMAND_PARTITE: TelegramCommandPolicy(
        command_key=COMMAND_PARTITE,
        tier="premium",
        entitlement_code=TELEGRAM_ENTITLEMENT_PARTITE,
    ),
    COMMAND_SCHEDINE: TelegramCommandPolicy(
        command_key=COMMAND_SCHEDINE,
        tier="premium",
        entitlement_code=TELEGRAM_ENTITLEMENT_SCHEDINE,
    ),
    COMMAND_STATISTICHE: TelegramCommandPolicy(
        command_key=COMMAND_STATISTICHE,
        tier="premium",
        entitlement_code=TELEGRAM_ENTITLEMENT_STATISTICHE,
    ),
}


def command_policy(command_key: str) -> TelegramCommandPolicy:
    key = (command_key or "").strip().lower()
    policy = _TELEGRAM_COMMAND_POLICIES.get(key)
    if policy is None:
        raise ValueError(f"Telegram command policy not configured: {command_key}")
    return policy


def _forced_reason_from_telegram_gate(reason: str | None) -> str:
    cleaned = (reason or "denied").strip().lower() or "denied"
    return f"telegram_{cleaned}"[:64]


def _upgrade_message(decision: AccessDecision) -> str:
    lines = ["Questo comando e disponibile solo con un piano premium attivo."]
    if decision.reason == "trial_expired":
        lines.append("Il periodo di prova risulta scaduto.")
    elif decision.reason in {"subscription_expired", "subscription_canceled"}:
        lines.append("Il tuo abbonamento premium non risulta attivo.")
    elif decision.reason == "missing_entitlement" and decision.plan_code:
        lines.append(f"Piano attuale: {decision.plan_code}.")

    upgrade_url = (get_settings().telegram_premium_upgrade_url or "").strip()
    if upgrade_url:
        lines.append(f"Upgrade: {upgrade_url}")
    else:
        lines.append("Contatta il supporto per attivare il piano premium.")
    return "\n".join(lines)


def _entitlement_denied_message(
    policy: TelegramCommandPolicy,
    decision: AccessDecision,
) -> str:
    premium_upgrade_reasons = {
        "missing_entitlement",
        "trial_expired",
        "subscription_expired",
        "subscription_canceled",
    }
    if policy.tier == "premium" and decision.reason in premium_upgrade_reasons:
        return _upgrade_message(decision)
    if decision.reason == "subscription_suspended":
        return (
            "Il tuo abbonamento premium e temporaneamente sospeso. "
            "Se hai avuto un pagamento non riuscito, usa /gestisci_abbonamento."
        )
    if decision.reason == "entitlement_check_error":
        return "Verifica abbonamento temporaneamente non disponibile. Riprova tra poco."
    return policy.denied_message or "Accesso non consentito."


def authorize_telegram_command_safe(
    *,
    telegram_user_id: int,
    policy: TelegramCommandPolicy,
    source: str = "telegram",
    resource: str = "unknown",
    context: dict[str, Any] | None = None,
) -> TelegramAuthorizationResult:
    telegram_gate = check_telegram_access_safe(telegram_user_id=telegram_user_id)

    entitlement_context = dict(context or {})
    entitlement_context.update(
        {
            "command_key": policy.command_key,
            "command_tier": policy.tier,
            "telegram_access_status": telegram_gate.status,
            "telegram_access_reason": telegram_gate.reason,
        }
    )

    forced_denial_reason = None
    if not telegram_gate.allowed:
        forced_denial_reason = _forced_reason_from_telegram_gate(telegram_gate.reason)

    decision = check_telegram_entitlement_safe(
        telegram_user_id=telegram_user_id,
        entitlement_code=policy.entitlement_code,
        source=source,
        resource=resource,
        forced_denial_reason=forced_denial_reason,
        context=entitlement_context,
    )

    if not telegram_gate.allowed:
        return TelegramAuthorizationResult(
            allowed=False,
            message=access_denial_message(telegram_gate),
            command_key=policy.command_key,
            tier=policy.tier,
            reason=telegram_gate.reason or decision.reason,
            plan_code=decision.plan_code,
            subscription_status=decision.subscription_status,
            trial_ends_at=decision.trial_ends_at,
            expires_at=decision.expires_at,
        )

    if not decision.allowed:
        return TelegramAuthorizationResult(
            allowed=False,
            message=_entitlement_denied_message(policy, decision),
            command_key=policy.command_key,
            tier=policy.tier,
            reason=decision.reason,
            plan_code=decision.plan_code,
            subscription_status=decision.subscription_status,
            trial_ends_at=decision.trial_ends_at,
            expires_at=decision.expires_at,
        )

    return TelegramAuthorizationResult(
        allowed=True,
        message=None,
        command_key=policy.command_key,
        tier=policy.tier,
        reason=None,
        plan_code=decision.plan_code,
        subscription_status=decision.subscription_status,
        trial_ends_at=decision.trial_ends_at,
        expires_at=decision.expires_at,
    )


def authorize_telegram_command_by_key_safe(
    *,
    telegram_user_id: int,
    command_key: str,
    source: str = "telegram",
    resource: str = "unknown",
    context: dict[str, Any] | None = None,
) -> TelegramAuthorizationResult:
    return authorize_telegram_command_safe(
        telegram_user_id=telegram_user_id,
        policy=command_policy(command_key),
        source=source,
        resource=resource,
        context=context,
    )



