"""Subscription domain services: plans, lifecycle, entitlements and access audit."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from backend.src.app.db.session import SessionLocal
from backend.src.app.schemas.subscriptions import (
    AccessDecision,
    PlanRead,
    SubscriptionRead,
    UserRead,
)
from backend.src.entity.subscription import (
    AccessLog,
    Entitlement,
    PaymentEvent,
    Plan,
    Subscription,
    User,
)

logger = logging.getLogger(__name__)

PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_FOUNDER = "founder"

SUB_STATUS_TRIALING = "trialing"
SUB_STATUS_ACTIVE = "active"
SUB_STATUS_CANCELED = "canceled"
SUB_STATUS_EXPIRED = "expired"
SUB_STATUS_SUSPENDED = "suspended"

TELEGRAM_ENTITLEMENT_PARTITE = "telegram.command.partite"
TELEGRAM_ENTITLEMENT_SCHEDINE = "telegram.command.schedine"
TELEGRAM_ENTITLEMENT_STATISTICHE = "telegram.command.statistiche"
TELEGRAM_ENTITLEMENT_FREE = "telegram.command.free"

_ACCESS_GRANTED_STATUSES = frozenset({SUB_STATUS_TRIALING, SUB_STATUS_ACTIVE})
_OPEN_SUBSCRIPTION_STATUSES = frozenset(
    {
        SUB_STATUS_TRIALING,
        SUB_STATUS_ACTIVE,
        SUB_STATUS_SUSPENDED,
    }
)

_DEFAULT_PLAN_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "code": PLAN_FREE,
        "name": "Free",
        "description": "Accesso base.",
        "status": "active",
        "billing_period_days": 30,
        "price_cents": 0,
        "currency": "EUR",
        "trial_days": 0,
        "is_default": True,
        "entitlements": {
            TELEGRAM_ENTITLEMENT_FREE: True,
            TELEGRAM_ENTITLEMENT_PARTITE: False,
            TELEGRAM_ENTITLEMENT_SCHEDINE: False,
            TELEGRAM_ENTITLEMENT_STATISTICHE: False,
            "telegram.notifications.manage": True,
            "feature.value_bet.deep_metrics": False,
            "feature.priority_support": False,
        },
    },
    {
        "code": PLAN_PRO,
        "name": "Pro",
        "description": "Accesso completo per utenti premium.",
        "status": "active",
        "billing_period_days": 30,
        "price_cents": 1900,
        "currency": "EUR",
        "trial_days": 7,
        "is_default": False,
        "entitlements": {
            TELEGRAM_ENTITLEMENT_FREE: True,
            TELEGRAM_ENTITLEMENT_PARTITE: True,
            TELEGRAM_ENTITLEMENT_SCHEDINE: True,
            TELEGRAM_ENTITLEMENT_STATISTICHE: True,
            "telegram.notifications.manage": True,
            "feature.value_bet.deep_metrics": True,
            "feature.priority_support": False,
        },
    },
    {
        "code": PLAN_FOUNDER,
        "name": "Founder",
        "description": "Piano founder con accesso premium e priorita supporto.",
        "status": "active",
        "billing_period_days": 3650,
        "price_cents": 0,
        "currency": "EUR",
        "trial_days": 0,
        "is_default": False,
        "entitlements": {
            TELEGRAM_ENTITLEMENT_FREE: True,
            TELEGRAM_ENTITLEMENT_PARTITE: True,
            TELEGRAM_ENTITLEMENT_SCHEDINE: True,
            TELEGRAM_ENTITLEMENT_STATISTICHE: True,
            "telegram.notifications.manage": True,
            "feature.value_bet.deep_metrics": True,
            "feature.priority_support": True,
        },
    },
)


class SubscriptionError(Exception):
    """Domain error for subscription operations."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class TelegramSubscriptionSnapshot:
    """Public-safe subscription overview for Telegram bot commands."""

    available: bool
    plan_code: str | None
    plan_name: str | None
    subscription_status: str | None
    trial_ends_at: datetime | None
    expires_at: datetime | None
    auto_renew: bool
    cancel_at_period_end: bool
    canceled_at: datetime | None
    payment_failed: bool


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_text(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def _to_user_read(row: User) -> UserRead:
    return UserRead.model_validate(row)


def _to_subscription_read(row: Subscription) -> SubscriptionRead:
    return SubscriptionRead.model_validate(row)


def _serialize_context(context: dict[str, Any] | None) -> str | None:
    if not context:
        return None
    try:
        return json.dumps(context, ensure_ascii=True, sort_keys=True)
    except TypeError:
        fallback = {key: str(value) for key, value in context.items()}
        return json.dumps(fallback, ensure_ascii=True, sort_keys=True)


def seed_default_plans(db: Session, *, commit: bool = True) -> list[PlanRead]:
    """Create/refresh baseline Free/Pro/Founder plans with entitlement matrix."""

    now = _utc_now_naive()
    mutated = False

    by_code = {
        plan.code: plan
        for plan in db.scalars(select(Plan)).all()
    }

    for definition in _DEFAULT_PLAN_CATALOG:
        code = definition["code"]
        plan = by_code.get(code)
        plan_changed = False
        if plan is None:
            plan = Plan(
                code=code,
                name=definition["name"],
                description=definition["description"],
                status=definition["status"],
                billing_period_days=int(definition["billing_period_days"]),
                price_cents=definition["price_cents"],
                currency=definition["currency"],
                trial_days=int(definition["trial_days"]),
                is_default=bool(definition["is_default"]),
                created_at=now,
                updated_at=now,
            )
            db.add(plan)
            db.flush()
            by_code[code] = plan
            mutated = True
            plan_changed = True
        else:
            if plan.name != definition["name"]:
                plan.name = definition["name"]
                mutated = True
                plan_changed = True
            if plan.description != definition["description"]:
                plan.description = definition["description"]
                mutated = True
                plan_changed = True
            if plan.status != definition["status"]:
                plan.status = definition["status"]
                mutated = True
                plan_changed = True
            if int(plan.billing_period_days or 0) != int(definition["billing_period_days"]):
                plan.billing_period_days = int(definition["billing_period_days"])
                mutated = True
                plan_changed = True
            if plan.price_cents != definition["price_cents"]:
                plan.price_cents = definition["price_cents"]
                mutated = True
                plan_changed = True
            if plan.currency != definition["currency"]:
                plan.currency = definition["currency"]
                mutated = True
                plan_changed = True
            if int(plan.trial_days or 0) != int(definition["trial_days"]):
                plan.trial_days = int(definition["trial_days"])
                mutated = True
                plan_changed = True
            if bool(plan.is_default) != bool(definition["is_default"]):
                plan.is_default = bool(definition["is_default"])
                mutated = True
                plan_changed = True
            if plan_changed:
                plan.updated_at = now

        entitlement_rows = db.scalars(
            select(Entitlement).where(Entitlement.plan_id == plan.id)
        ).all()
        entitlement_by_code = {row.code: row for row in entitlement_rows}

        for entitlement_code, is_enabled in definition["entitlements"].items():
            row = entitlement_by_code.get(entitlement_code)
            if row is None:
                db.add(
                    Entitlement(
                        plan_id=plan.id,
                        code=entitlement_code,
                        is_enabled=bool(is_enabled),
                        value=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                mutated = True
                continue
            if bool(row.is_enabled) != bool(is_enabled):
                row.is_enabled = bool(is_enabled)
                row.updated_at = now
                mutated = True

    if mutated:
        if commit:
            db.commit()
        else:
            db.flush()

    ordered: list[PlanRead] = []
    for definition in _DEFAULT_PLAN_CATALOG:
        code = definition["code"]
        result = db.execute(
            select(Plan)
            .options(joinedload(Plan.entitlements))
            .where(Plan.code == code)
        )
        row = result.unique().scalar_one()
        ordered.append(PlanRead.model_validate(row))
    return ordered


def _get_user_by_id(db: Session, user_id: int) -> User:
    row = db.scalar(select(User).where(User.id == user_id))
    if row is None:
        raise SubscriptionError("User non trovato.", status_code=404)
    return row


def _get_plan_by_code(db: Session, plan_code: str) -> Plan:
    cleaned = (plan_code or "").strip().lower()
    row = db.scalar(select(Plan).where(Plan.code == cleaned))
    if row is None:
        raise SubscriptionError(f"Piano non trovato: {plan_code}", status_code=404)
    return row


def get_user_by_telegram_id(db: Session, telegram_user_id: int) -> User | None:
    return db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))


def get_or_create_user(
    db: Session,
    *,
    telegram_user_id: int | None = None,
    external_ref: str | None = None,
    username: str | None = None,
    now: datetime | None = None,
) -> UserRead:
    """Upsert a subscription user by Telegram id and/or external reference."""

    cleaned_external_ref = _normalize_text(external_ref, 191)
    cleaned_username = _normalize_text(username, 255)
    if telegram_user_id is None and cleaned_external_ref is None:
        raise SubscriptionError(
            "Serve telegram_user_id o external_ref per creare/recuperare l'utente.",
            status_code=400,
        )

    resolved_now = now or _utc_now_naive()
    clauses = []
    if telegram_user_id is not None:
        clauses.append(User.telegram_user_id == telegram_user_id)
    if cleaned_external_ref is not None:
        clauses.append(User.external_ref == cleaned_external_ref)

    row = db.scalar(select(User).where(or_(*clauses)).order_by(User.id.asc()))
    if row is None:
        row = User(
            telegram_user_id=telegram_user_id,
            external_ref=cleaned_external_ref,
            username=cleaned_username,
            status="active",
            created_at=resolved_now,
            updated_at=resolved_now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_user_read(row)

    changed = False
    if telegram_user_id is not None and row.telegram_user_id != telegram_user_id:
        row.telegram_user_id = telegram_user_id
        changed = True
    if cleaned_external_ref is not None and row.external_ref != cleaned_external_ref:
        row.external_ref = cleaned_external_ref
        changed = True
    if cleaned_username is not None and row.username != cleaned_username:
        row.username = cleaned_username
        changed = True

    if changed:
        row.updated_at = resolved_now
        db.commit()
        db.refresh(row)

    return _to_user_read(row)


def list_user_subscriptions(db: Session, *, user_id: int) -> list[SubscriptionRead]:
    rows = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.started_at.desc(), Subscription.id.desc())
    ).unique().scalars().all()
    return [_to_subscription_read(row) for row in rows]


def get_telegram_subscription_snapshot(
    db: Session,
    *,
    telegram_user_id: int,
    at: datetime | None = None,
    auto_create_user: bool = True,
) -> TelegramSubscriptionSnapshot:
    """Resolve the current subscription status used by /piano and related bot commands."""

    if int(telegram_user_id) <= 0:
        raise SubscriptionError("telegram_user_id non valido.", status_code=400)

    resolved_at = at or _utc_now_naive()
    seed_default_plans(db)
    expire_due_subscriptions(db, at=resolved_at, commit=False)

    user = get_user_by_telegram_id(db, int(telegram_user_id))
    if user is None and auto_create_user:
        created = get_or_create_user(
            db,
            telegram_user_id=int(telegram_user_id),
            now=resolved_at,
        )
        user = db.scalar(select(User).where(User.id == created.id))

    if user is None:
        db.commit()
        return TelegramSubscriptionSnapshot(
            available=False,
            plan_code=None,
            plan_name=None,
            subscription_status=None,
            trial_ends_at=None,
            expires_at=None,
            auto_renew=False,
            cancel_at_period_end=False,
            canceled_at=None,
            payment_failed=False,
        )

    subscription = _resolve_current_subscription(db, user_id=user.id, at=resolved_at)
    if subscription is None:
        subscription = _ensure_free_subscription(db, user=user, at=resolved_at)

    subscription = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(Subscription.id == subscription.id)
    ).unique().scalar_one()

    display_subscription = subscription
    latest_non_free = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Subscription.user_id == user.id,
            Plan.code != PLAN_FREE,
        )
        .order_by(Subscription.started_at.desc(), Subscription.id.desc())
    ).unique().scalars().first()
    if (
        subscription.plan is not None
        and subscription.plan.code == PLAN_FREE
        and latest_non_free is not None
        and latest_non_free.status in {SUB_STATUS_EXPIRED, SUB_STATUS_CANCELED, SUB_STATUS_SUSPENDED}
    ):
        display_subscription = latest_non_free

    latest_failed_event = db.scalar(
        select(PaymentEvent.id)
        .where(
            PaymentEvent.subscription_id == display_subscription.id,
            PaymentEvent.status == "failed",
        )
        .order_by(PaymentEvent.event_at.desc(), PaymentEvent.id.desc())
    )

    db.commit()
    return TelegramSubscriptionSnapshot(
        available=True,
        plan_code=display_subscription.plan.code if display_subscription.plan is not None else None,
        plan_name=display_subscription.plan.name if display_subscription.plan is not None else None,
        subscription_status=display_subscription.status,
        trial_ends_at=display_subscription.trial_ends_at,
        expires_at=display_subscription.expires_at,
        auto_renew=bool(display_subscription.auto_renew),
        cancel_at_period_end=bool(display_subscription.cancel_at_period_end),
        canceled_at=display_subscription.canceled_at,
        payment_failed=latest_failed_event is not None,
    )


def get_telegram_subscription_snapshot_safe(
    *,
    telegram_user_id: int,
    at: datetime | None = None,
) -> TelegramSubscriptionSnapshot:
    """Safe wrapper around Telegram subscription snapshot resolution."""

    try:
        with SessionLocal() as db:
            return get_telegram_subscription_snapshot(
                db,
                telegram_user_id=telegram_user_id,
                at=at,
                auto_create_user=True,
            )
    except Exception:
        logger.exception(
            "Telegram subscription snapshot failed telegram_user_id=%s",
            telegram_user_id,
        )
        return TelegramSubscriptionSnapshot(
            available=False,
            plan_code=None,
            plan_name=None,
            subscription_status=None,
            trial_ends_at=None,
            expires_at=None,
            auto_renew=False,
            cancel_at_period_end=False,
            canceled_at=None,
            payment_failed=False,
        )


def _create_payment_event(
    db: Session,
    *,
    subscription: Subscription,
    user_id: int,
    provider: str,
    provider_event_id: str | None,
    event_type: str,
    status: str,
    amount_cents: int | None,
    currency: str | None,
    event_at: datetime,
    payload: dict[str, Any] | None = None,
) -> None:
    event = PaymentEvent(
        subscription_id=subscription.id,
        user_id=user_id,
        provider=_normalize_text(provider, 64) or "manual",
        provider_event_id=_normalize_text(provider_event_id, 191),
        event_type=_normalize_text(event_type, 64) or "event",
        status=_normalize_text(status, 32) or "pending",
        amount_cents=amount_cents,
        currency=_normalize_text(currency, 8),
        event_at=event_at,
        raw_payload_json=_serialize_context(payload),
        created_at=event_at,
    )
    db.add(event)


def expire_due_subscriptions(
    db: Session,
    *,
    at: datetime | None = None,
    commit: bool = True,
) -> int:
    """Mark expired rows when ``expires_at`` is reached."""

    resolved_at = at or _utc_now_naive()
    rows = db.scalars(
        select(Subscription).where(
            Subscription.status.in_(_OPEN_SUBSCRIPTION_STATUSES),
            Subscription.expires_at.is_not(None),
            Subscription.expires_at <= resolved_at,
        )
    ).all()

    if not rows:
        return 0

    for row in rows:
        row.status = SUB_STATUS_EXPIRED
        if row.current_period_end_at is None:
            row.current_period_end_at = row.expires_at
        row.auto_renew = False
        row.cancel_at_period_end = False
        row.updated_at = resolved_at

    if commit:
        db.commit()
    else:
        db.flush()
    return len(rows)


def _resolve_current_subscription(
    db: Session,
    *,
    user_id: int,
    at: datetime,
) -> Subscription | None:
    rows = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(
            Subscription.user_id == user_id,
            Subscription.status.in_(_OPEN_SUBSCRIPTION_STATUSES),
            Subscription.started_at <= at,
        )
        .order_by(Subscription.started_at.desc(), Subscription.id.desc())
    ).unique().scalars().all()

    for row in rows:
        if row.expires_at is None or row.expires_at > at:
            return row
    return None


def _ensure_free_subscription(
    db: Session,
    *,
    user: User,
    at: datetime,
) -> Subscription:
    plan = _get_plan_by_code(db, PLAN_FREE)

    existing = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(
            Subscription.user_id == user.id,
            Subscription.plan_id == plan.id,
            Subscription.status.in_(_OPEN_SUBSCRIPTION_STATUSES),
        )
        .order_by(Subscription.started_at.desc(), Subscription.id.desc())
    ).unique().scalars().first()
    if existing is not None and (existing.expires_at is None or existing.expires_at > at):
        return existing

    row = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status=SUB_STATUS_ACTIVE,
        started_at=at,
        current_period_start_at=at,
        current_period_end_at=None,
        trial_started_at=None,
        trial_ends_at=None,
        renewed_at=None,
        expires_at=None,
        auto_renew=False,
        cancel_at_period_end=False,
        canceled_at=None,
        cancellation_reason=None,
        suspended_at=None,
        suspension_reason=None,
        created_at=at,
        updated_at=at,
    )
    db.add(row)
    db.flush()

    _create_payment_event(
        db,
        subscription=row,
        user_id=user.id,
        provider="system",
        provider_event_id=None,
        event_type="subscription_started",
        status="succeeded",
        amount_cents=0,
        currency=plan.currency,
        event_at=at,
        payload={"plan_code": plan.code, "auto_provisioned": True},
    )
    db.flush()
    db.refresh(row)
    return row


def create_subscription(
    db: Session,
    *,
    user_id: int,
    plan_code: str,
    started_at: datetime | None = None,
    trial_days: int | None = None,
    period_days: int | None = None,
    now: datetime | None = None,
    provider: str = "manual",
    provider_event_id: str | None = None,
    commit: bool = True,
) -> SubscriptionRead:
    """Start a new subscription and close any currently open one."""

    seed_default_plans(db, commit=commit)
    resolved_now = now or _utc_now_naive()
    resolved_started_at = started_at or resolved_now

    expire_due_subscriptions(db, at=resolved_now, commit=False)
    user = _get_user_by_id(db, user_id)
    plan = _get_plan_by_code(db, plan_code)

    current = _resolve_current_subscription(db, user_id=user.id, at=resolved_now)
    if current is not None:
        current.status = SUB_STATUS_CANCELED
        current.canceled_at = resolved_now
        current.cancellation_reason = "replaced_by_new_subscription"
        current.current_period_end_at = resolved_now
        current.expires_at = resolved_now
        current.auto_renew = False
        current.cancel_at_period_end = False
        current.updated_at = resolved_now

    resolved_trial_days = max(0, int(trial_days if trial_days is not None else plan.trial_days or 0))

    if period_days is None and plan.code == PLAN_FREE:
        resolved_period_days = None
    else:
        resolved_period_days = max(1, int(period_days if period_days is not None else plan.billing_period_days or 1))

    if resolved_period_days is not None:
        period_end = resolved_started_at + timedelta(days=resolved_period_days)
    else:
        period_end = None

    row = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status=SUB_STATUS_TRIALING if resolved_trial_days > 0 else SUB_STATUS_ACTIVE,
        started_at=resolved_started_at,
        current_period_start_at=resolved_started_at,
        current_period_end_at=period_end,
        trial_started_at=resolved_started_at if resolved_trial_days > 0 else None,
        trial_ends_at=(
            resolved_started_at + timedelta(days=resolved_trial_days)
            if resolved_trial_days > 0
            else None
        ),
        renewed_at=None,
        expires_at=period_end,
        auto_renew=plan.code != PLAN_FREE,
        cancel_at_period_end=False,
        canceled_at=None,
        cancellation_reason=None,
        suspended_at=None,
        suspension_reason=None,
        created_at=resolved_now,
        updated_at=resolved_now,
    )
    db.add(row)
    db.flush()

    _create_payment_event(
        db,
        subscription=row,
        user_id=user.id,
        provider=provider,
        provider_event_id=provider_event_id,
        event_type="trial_started" if resolved_trial_days > 0 else "subscription_started",
        status="succeeded",
        amount_cents=0 if resolved_trial_days > 0 else plan.price_cents,
        currency=plan.currency,
        event_at=resolved_now,
        payload={
            "plan_code": plan.code,
            "trial_days": resolved_trial_days,
            "period_days": resolved_period_days,
        },
    )

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _to_subscription_read(row)


def renew_subscription(
    db: Session,
    subscription_id: int,
    *,
    period_days: int | None = None,
    now: datetime | None = None,
    provider: str = "manual",
    provider_event_id: str | None = None,
    amount_cents: int | None = None,
    currency: str | None = None,
    commit: bool = True,
) -> SubscriptionRead:
    """Renew an existing subscription period and move it to active."""

    resolved_now = now or _utc_now_naive()
    row = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(Subscription.id == subscription_id)
    ).unique().scalar_one_or_none()
    if row is None:
        raise SubscriptionError("Subscription non trovata.", status_code=404)

    plan = row.plan
    base_days = period_days if period_days is not None else int((plan.billing_period_days if plan else 30) or 30)
    resolved_days = max(1, int(base_days))

    anchor = row.expires_at if row.expires_at and row.expires_at > resolved_now else resolved_now
    new_end = anchor + timedelta(days=resolved_days)

    row.status = SUB_STATUS_ACTIVE
    row.current_period_start_at = anchor
    row.current_period_end_at = new_end
    row.expires_at = new_end
    row.renewed_at = resolved_now
    row.auto_renew = True
    row.cancel_at_period_end = False
    row.suspended_at = None
    row.suspension_reason = None
    row.updated_at = resolved_now

    _create_payment_event(
        db,
        subscription=row,
        user_id=row.user_id,
        provider=provider,
        provider_event_id=provider_event_id,
        event_type="renewed",
        status="succeeded",
        amount_cents=amount_cents if amount_cents is not None else (plan.price_cents if plan else None),
        currency=currency or (plan.currency if plan else None),
        event_at=resolved_now,
        payload={"period_days": resolved_days},
    )

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _to_subscription_read(row)


def cancel_subscription(
    db: Session,
    subscription_id: int,
    *,
    immediate: bool = False,
    reason: str | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> SubscriptionRead:
    """Cancel now or at period end."""

    resolved_now = now or _utc_now_naive()
    row = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(Subscription.id == subscription_id)
    ).unique().scalar_one_or_none()
    if row is None:
        raise SubscriptionError("Subscription non trovata.", status_code=404)

    row.canceled_at = resolved_now
    row.cancellation_reason = _normalize_text(reason, 255)
    row.auto_renew = False

    if immediate or (row.current_period_end_at is None and row.expires_at is None):
        row.status = SUB_STATUS_CANCELED
        row.current_period_end_at = resolved_now
        row.expires_at = resolved_now
        row.cancel_at_period_end = False
    else:
        row.cancel_at_period_end = True

    row.updated_at = resolved_now

    _create_payment_event(
        db,
        subscription=row,
        user_id=row.user_id,
        provider="system",
        provider_event_id=None,
        event_type="canceled_immediate" if row.status == SUB_STATUS_CANCELED else "canceled_at_period_end",
        status="succeeded",
        amount_cents=None,
        currency=row.plan.currency if row.plan else None,
        event_at=resolved_now,
        payload={"immediate": row.status == SUB_STATUS_CANCELED},
    )

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _to_subscription_read(row)


def suspend_subscription(
    db: Session,
    subscription_id: int,
    *,
    reason: str | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> SubscriptionRead:
    """Suspend an active/trialing subscription."""

    resolved_now = now or _utc_now_naive()
    row = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(Subscription.id == subscription_id)
    ).unique().scalar_one_or_none()
    if row is None:
        raise SubscriptionError("Subscription non trovata.", status_code=404)

    row.status = SUB_STATUS_SUSPENDED
    row.suspended_at = resolved_now
    row.suspension_reason = _normalize_text(reason, 255)
    row.updated_at = resolved_now

    _create_payment_event(
        db,
        subscription=row,
        user_id=row.user_id,
        provider="system",
        provider_event_id=None,
        event_type="suspended",
        status="succeeded",
        amount_cents=None,
        currency=row.plan.currency if row.plan else None,
        event_at=resolved_now,
        payload={"reason": row.suspension_reason},
    )

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _to_subscription_read(row)


def resume_subscription(
    db: Session,
    subscription_id: int,
    *,
    now: datetime | None = None,
    commit: bool = True,
) -> SubscriptionRead:
    """Resume a suspended subscription when still within expiration date."""

    resolved_now = now or _utc_now_naive()
    row = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(Subscription.id == subscription_id)
    ).unique().scalar_one_or_none()
    if row is None:
        raise SubscriptionError("Subscription non trovata.", status_code=404)

    if row.status != SUB_STATUS_SUSPENDED:
        return _to_subscription_read(row)

    if row.expires_at is not None and row.expires_at <= resolved_now:
        row.status = SUB_STATUS_EXPIRED
    elif row.trial_ends_at is not None and row.trial_ends_at > resolved_now:
        row.status = SUB_STATUS_TRIALING
    else:
        row.status = SUB_STATUS_ACTIVE

    row.suspended_at = None
    row.suspension_reason = None
    row.updated_at = resolved_now

    _create_payment_event(
        db,
        subscription=row,
        user_id=row.user_id,
        provider="system",
        provider_event_id=None,
        event_type="resumed",
        status="succeeded",
        amount_cents=None,
        currency=row.plan.currency if row.plan else None,
        event_at=resolved_now,
    )

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return _to_subscription_read(row)


def _plan_has_entitlement(db: Session, *, plan_id: int, entitlement_code: str) -> bool:
    row = db.scalar(
        select(Entitlement).where(
            Entitlement.plan_id == plan_id,
            Entitlement.code == entitlement_code,
        )
    )
    return bool(row and row.is_enabled)


def _log_access(
    db: Session,
    *,
    user_id: int | None,
    subscription_id: int | None,
    plan_code: str | None,
    source: str,
    resource: str,
    entitlement_code: str,
    allowed: bool,
    reason: str | None,
    requested_at: datetime,
    context: dict[str, Any] | None,
) -> None:
    db.add(
        AccessLog(
            user_id=user_id,
            subscription_id=subscription_id,
            plan_code=_normalize_text(plan_code, 32),
            source=_normalize_text(source, 64) or "unknown",
            resource=_normalize_text(resource, 128) or "unknown",
            entitlement_code=_normalize_text(entitlement_code, 128),
            allowed=allowed,
            reason=_normalize_text(reason, 64),
            requested_at=requested_at,
            context_json=_serialize_context(context),
        )
    )


def check_user_entitlement(
    db: Session,
    *,
    entitlement_code: str,
    user_id: int | None = None,
    telegram_user_id: int | None = None,
    source: str = "api",
    resource: str = "unknown",
    at: datetime | None = None,
    auto_create_user: bool = False,
    forced_denial_reason: str | None = None,
    context: dict[str, Any] | None = None,
) -> AccessDecision:
    """Resolve access from subscription+plan entitlements and write an access log row."""

    cleaned_entitlement = _normalize_text(entitlement_code, 128)
    if cleaned_entitlement is None:
        raise SubscriptionError("entitlement_code obbligatorio.", status_code=400)

    seed_default_plans(db)
    resolved_at = at or _utc_now_naive()
    expire_due_subscriptions(db, at=resolved_at, commit=False)

    row_user: User | None = None
    if user_id is not None:
        row_user = db.scalar(select(User).where(User.id == user_id))
    elif telegram_user_id is not None:
        row_user = get_user_by_telegram_id(db, telegram_user_id)
        if row_user is None and auto_create_user:
            created = get_or_create_user(
                db,
                telegram_user_id=telegram_user_id,
                now=resolved_at,
            )
            row_user = db.scalar(select(User).where(User.id == created.id))
    else:
        raise SubscriptionError("Serve user_id o telegram_user_id.", status_code=400)

    if row_user is None:
        denied_reason = _normalize_text(forced_denial_reason, 64) or "user_not_found"
        decision = AccessDecision(
            allowed=False,
            reason=denied_reason,
            entitlement_code=cleaned_entitlement,
            user_id=None,
            subscription_id=None,
            plan_code=None,
            subscription_status=None,
            trial_ends_at=None,
            expires_at=None,
            checked_at=resolved_at,
        )
        _log_access(
            db,
            user_id=None,
            subscription_id=None,
            plan_code=None,
            source=source,
            resource=resource,
            entitlement_code=cleaned_entitlement,
            allowed=decision.allowed,
            reason=decision.reason,
            requested_at=resolved_at,
            context=context,
        )
        db.commit()
        return decision

    subscription = _resolve_current_subscription(db, user_id=row_user.id, at=resolved_at)
    if subscription is None:
        subscription = _ensure_free_subscription(db, user=row_user, at=resolved_at)

    plan_code = subscription.plan.code if subscription.plan is not None else None
    trial_ends_at = subscription.trial_ends_at
    expires_at = subscription.expires_at
    reason: str | None = None
    allowed = False

    forced_reason = _normalize_text(forced_denial_reason, 64)
    if forced_reason:
        reason = forced_reason
    elif subscription.status == SUB_STATUS_SUSPENDED:
        reason = "subscription_suspended"
    elif expires_at is not None and expires_at <= resolved_at:
        reason = "subscription_expired"
    elif (
        subscription.status == SUB_STATUS_TRIALING
        and trial_ends_at is not None
        and trial_ends_at <= resolved_at
    ):
        reason = "trial_expired"
    elif subscription.status not in _ACCESS_GRANTED_STATUSES:
        reason = f"subscription_{subscription.status}"
    elif _plan_has_entitlement(
        db,
        plan_id=subscription.plan_id,
        entitlement_code=cleaned_entitlement,
    ):
        allowed = True
    else:
        reason = "missing_entitlement"

    decision = AccessDecision(
        allowed=allowed,
        reason=reason,
        entitlement_code=cleaned_entitlement,
        user_id=row_user.id,
        subscription_id=subscription.id,
        plan_code=plan_code,
        subscription_status=subscription.status,
        trial_ends_at=trial_ends_at,
        expires_at=expires_at,
        checked_at=resolved_at,
    )

    _log_access(
        db,
        user_id=row_user.id,
        subscription_id=subscription.id,
        plan_code=plan_code,
        source=source,
        resource=resource,
        entitlement_code=cleaned_entitlement,
        allowed=allowed,
        reason=reason,
        requested_at=resolved_at,
        context=context,
    )
    db.commit()
    return decision


def check_telegram_entitlement_safe(
    *,
    telegram_user_id: int,
    entitlement_code: str,
    source: str = "telegram",
    resource: str = "unknown",
    forced_denial_reason: str | None = None,
    context: dict[str, Any] | None = None,
) -> AccessDecision:
    """Safe helper for Telegram handlers (auto-provision user on first check)."""

    try:
        with SessionLocal() as db:
            return check_user_entitlement(
                db,
                entitlement_code=entitlement_code,
                telegram_user_id=telegram_user_id,
                source=source,
                resource=resource,
                auto_create_user=True,
                forced_denial_reason=forced_denial_reason,
                context=context,
            )
    except Exception:
        logger.exception(
            "Subscription entitlement check failed telegram_user_id=%s entitlement=%s",
            telegram_user_id,
            entitlement_code,
        )
        return AccessDecision(
            allowed=False,
            reason="entitlement_check_error",
            entitlement_code=entitlement_code,
            user_id=None,
            subscription_id=None,
            plan_code=None,
            subscription_status=None,
            checked_at=_utc_now_naive(),
        )


