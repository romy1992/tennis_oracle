"""Payment orchestration on top of a provider abstraction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.db.session import SessionLocal
from backend.src.app.schemas.payments import (
    PaymentCheckoutRead,
    PaymentCustomerPortalRead,
    PaymentWebhookAck,
)
from backend.src.app.services.payment_provider import (
    PaymentProvider,
    PaymentProviderError,
    ProviderWebhookEvent,
    StripePaymentProvider,
)
from backend.src.app.services.subscriptions import (
    PLAN_PRO,
    SubscriptionError,
    cancel_subscription,
    create_subscription,
    get_or_create_user,
    renew_subscription,
    seed_default_plans,
)
from backend.src.entity.subscription import (
    PaymentCheckoutSession,
    PaymentCustomer,
    PaymentEvent,
    Plan,
    Subscription,
    User,
)

PAYMENT_PROVIDER_STRIPE = "stripe"
BILLING_CYCLE_MONTHLY = "monthly"
BILLING_CYCLE_YEARLY = "yearly"

_SUPPORTED_BILLING_CYCLES = frozenset({BILLING_CYCLE_MONTHLY, BILLING_CYCLE_YEARLY})
_OPEN_SUBSCRIPTION_STATUSES = frozenset({"trialing", "active", "suspended"})
_STRIPE_SUSPENDED_STATUSES = frozenset({"past_due", "unpaid", "incomplete", "paused"})
_STRIPE_CANCELED_STATUSES = frozenset({"canceled", "incomplete_expired"})


class PaymentServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_checkout_session_for_telegram_user(
    db: Session,
    *,
    telegram_user_id: int,
    username: str | None,
    plan_code: str,
    billing_cycle: str,
    success_url: str | None,
    cancel_url: str | None,
    idempotency_key: str | None,
    settings: Settings | None = None,
    provider_override: PaymentProvider | None = None,
    now: datetime | None = None,
) -> PaymentCheckoutRead:
    """Create an idempotent checkout session linked to a Telegram user."""

    resolved_settings = settings or get_settings()
    provider = _resolve_provider(
        settings=resolved_settings,
        provider_override=provider_override,
        expected_provider_name=None,
    )
    resolved_now = now or _utc_now_naive()

    resolved_billing_cycle = _normalize_billing_cycle(billing_cycle)
    if resolved_billing_cycle is None:
        raise PaymentServiceError("billing_cycle non valido.", status_code=400)

    resolved_plan_code = _normalize_text(plan_code, 32)
    if resolved_plan_code is None:
        raise PaymentServiceError("plan_code obbligatorio.", status_code=400)

    seed_default_plans(db)
    plan = db.scalar(select(Plan).where(Plan.code == resolved_plan_code))
    if plan is None:
        raise PaymentServiceError("Piano non trovato.", status_code=404)
    if resolved_plan_code != PLAN_PRO:
        raise PaymentServiceError(
            "Checkout provider supportato solo per il piano pro.",
            status_code=400,
        )

    user_read = get_or_create_user(
        db,
        telegram_user_id=telegram_user_id,
        username=username,
        now=resolved_now,
    )
    user = db.scalar(select(User).where(User.id == user_read.id))
    if user is None:
        raise PaymentServiceError("Utente non trovato.", status_code=404)

    customer = _ensure_provider_customer(
        db,
        user=user,
        provider=provider,
        resolved_now=resolved_now,
    )

    resolved_success_url, resolved_cancel_url = _resolve_checkout_urls(
        settings=resolved_settings,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    resolved_idempotency_key = _resolve_idempotency_key(
        idempotency_key=idempotency_key,
        user_id=user.id,
        plan_code=resolved_plan_code,
        billing_cycle=resolved_billing_cycle,
        now=resolved_now,
        settings=resolved_settings,
    )

    existing = db.execute(
        select(PaymentCheckoutSession)
        .options(joinedload(PaymentCheckoutSession.customer))
        .where(
            PaymentCheckoutSession.provider == provider.provider_name,
            PaymentCheckoutSession.idempotency_key == resolved_idempotency_key,
        )
    ).unique().scalar_one_or_none()
    if existing is not None and existing.checkout_url and existing.provider_session_id:
        return _checkout_read(existing, mode=resolved_settings.payments_mode, reused=True)

    price_id = _resolve_price_id_for_cycle(resolved_settings, resolved_billing_cycle)
    metadata = {
        "app_user_id": str(user.id),
        "telegram_user_id": str(user.telegram_user_id or ""),
        "plan_code": resolved_plan_code,
        "billing_cycle": resolved_billing_cycle,
    }

    try:
        provider_session = provider.create_checkout_session(
            external_user_id=str(user.id),
            customer_id=customer.provider_customer_id,
            price_id=price_id,
            success_url=resolved_success_url,
            cancel_url=resolved_cancel_url,
            metadata=metadata,
            idempotency_key=resolved_idempotency_key,
        )
    except PaymentProviderError as exc:
        raise PaymentServiceError(exc.message, status_code=exc.status_code) from exc

    if existing is None:
        row = PaymentCheckoutSession(
            user_id=user.id,
            customer_id=customer.id,
            provider=provider.provider_name,
            idempotency_key=resolved_idempotency_key,
            provider_session_id=provider_session.session_id,
            provider_subscription_id=None,
            plan_code=resolved_plan_code,
            billing_cycle=resolved_billing_cycle,
            status="created",
            checkout_url=provider_session.checkout_url,
            expires_at=provider_session.expires_at,
            completed_at=None,
            canceled_at=None,
            raw_payload_json=_serialize_payload(provider_session.raw_payload),
            created_at=resolved_now,
            updated_at=resolved_now,
        )
        db.add(row)
    else:
        row = existing
        row.customer_id = customer.id
        row.provider_session_id = provider_session.session_id
        row.plan_code = resolved_plan_code
        row.billing_cycle = resolved_billing_cycle
        row.status = "created"
        row.checkout_url = provider_session.checkout_url
        row.expires_at = provider_session.expires_at
        row.raw_payload_json = _serialize_payload(provider_session.raw_payload)
        row.updated_at = resolved_now

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        conflicted = db.execute(
            select(PaymentCheckoutSession)
            .options(joinedload(PaymentCheckoutSession.customer))
            .where(
                PaymentCheckoutSession.provider == provider.provider_name,
                PaymentCheckoutSession.idempotency_key == resolved_idempotency_key,
            )
        ).unique().scalar_one_or_none()
        if conflicted is not None and conflicted.checkout_url and conflicted.provider_session_id:
            return _checkout_read(conflicted, mode=resolved_settings.payments_mode, reused=True)
        raise PaymentServiceError(
            "Conflitto idempotenza durante la creazione checkout.",
            status_code=409,
        ) from exc

    db.refresh(row)
    row = db.execute(
        select(PaymentCheckoutSession)
        .options(joinedload(PaymentCheckoutSession.customer))
        .where(PaymentCheckoutSession.id == row.id)
    ).unique().scalar_one()
    return _checkout_read(row, mode=resolved_settings.payments_mode, reused=False)


def create_customer_portal_session_for_telegram_user(
    db: Session,
    *,
    telegram_user_id: int,
    username: str | None,
    return_url: str | None,
    idempotency_key: str | None,
    settings: Settings | None = None,
    provider_override: PaymentProvider | None = None,
    now: datetime | None = None,
) -> PaymentCustomerPortalRead:
    """Create a short-lived customer portal session for the Telegram user."""

    resolved_settings = settings or get_settings()
    provider = _resolve_provider(
        settings=resolved_settings,
        provider_override=provider_override,
        expected_provider_name=None,
    )
    resolved_now = now or _utc_now_naive()

    user_read = get_or_create_user(
        db,
        telegram_user_id=telegram_user_id,
        username=username,
        now=resolved_now,
    )
    user = db.scalar(select(User).where(User.id == user_read.id))
    if user is None:
        raise PaymentServiceError("Utente non trovato.", status_code=404)

    customer = db.scalar(
        select(PaymentCustomer).where(
            PaymentCustomer.user_id == user.id,
            PaymentCustomer.provider == provider.provider_name,
        )
    )
    if customer is None:
        raise PaymentServiceError(
            "Nessun abbonamento gestibile trovato. Usa /abbonati per attivarlo.",
            status_code=404,
        )

    resolved_return_url = _resolve_portal_return_url(
        settings=resolved_settings,
        return_url=return_url,
    )
    resolved_idempotency_key = _resolve_portal_idempotency_key(
        idempotency_key=idempotency_key,
        user_id=user.id,
        provider_name=provider.provider_name,
        now=resolved_now,
        settings=resolved_settings,
    )

    try:
        portal_session = provider.create_customer_portal_session(
            external_user_id=str(user.id),
            customer_id=customer.provider_customer_id,
            return_url=resolved_return_url,
            idempotency_key=resolved_idempotency_key,
        )
    except PaymentProviderError as exc:
        raise PaymentServiceError(exc.message, status_code=exc.status_code) from exc

    ttl_seconds = _resolve_portal_ttl_seconds(resolved_settings)
    return PaymentCustomerPortalRead(
        provider=portal_session.provider,
        mode=(resolved_settings.payments_mode or "sandbox"),
        portal_url=portal_session.portal_url,
        expires_at=resolved_now + timedelta(seconds=ttl_seconds),
    )


def create_checkout_session_for_telegram_user_safe(
    *,
    telegram_user_id: int,
    username: str | None,
    plan_code: str,
    billing_cycle: str,
    success_url: str | None,
    cancel_url: str | None,
    idempotency_key: str | None,
    settings: Settings | None = None,
    provider_override: PaymentProvider | None = None,
    now: datetime | None = None,
) -> PaymentCheckoutRead:
    """Safe DB-session wrapper around checkout creation for Telegram handlers."""

    try:
        with SessionLocal() as db:
            return create_checkout_session_for_telegram_user(
                db,
                telegram_user_id=telegram_user_id,
                username=username,
                plan_code=plan_code,
                billing_cycle=billing_cycle,
                success_url=success_url,
                cancel_url=cancel_url,
                idempotency_key=idempotency_key,
                settings=settings,
                provider_override=provider_override,
                now=now,
            )
    except PaymentServiceError:
        raise
    except Exception as exc:
        raise PaymentServiceError(
            "Checkout temporaneamente non disponibile.",
            status_code=503,
        ) from exc


def create_customer_portal_session_for_telegram_user_safe(
    *,
    telegram_user_id: int,
    username: str | None,
    return_url: str | None,
    idempotency_key: str | None,
    settings: Settings | None = None,
    provider_override: PaymentProvider | None = None,
    now: datetime | None = None,
) -> PaymentCustomerPortalRead:
    """Safe DB-session wrapper around customer-portal session creation for Telegram handlers."""

    try:
        with SessionLocal() as db:
            return create_customer_portal_session_for_telegram_user(
                db,
                telegram_user_id=telegram_user_id,
                username=username,
                return_url=return_url,
                idempotency_key=idempotency_key,
                settings=settings,
                provider_override=provider_override,
                now=now,
            )
    except PaymentServiceError:
        raise
    except Exception as exc:
        raise PaymentServiceError(
            "Portale abbonamento temporaneamente non disponibile.",
            status_code=503,
        ) from exc


def process_stripe_webhook(
    db: Session,
    *,
    payload: bytes,
    signature_header: str | None,
    settings: Settings | None = None,
    provider_override: PaymentProvider | None = None,
) -> PaymentWebhookAck:
    """Verify and process Stripe webhook events with deduplication."""

    resolved_settings = settings or get_settings()
    provider = _resolve_provider(
        settings=resolved_settings,
        provider_override=provider_override,
        expected_provider_name=PAYMENT_PROVIDER_STRIPE,
    )

    try:
        event = provider.parse_webhook(
            payload=payload,
            signature_header=signature_header,
            tolerance_seconds=max(0, int(resolved_settings.stripe_webhook_tolerance_seconds)),
        )
    except PaymentProviderError as exc:
        raise PaymentServiceError(exc.message, status_code=exc.status_code) from exc

    handler = _WEBHOOK_HANDLERS.get(event.event_type)
    if handler is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="ignored_event_type",
        )

    if _event_already_processed(db, event_id=event.event_id):
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            duplicate=True,
            message="duplicate_event",
        )

    try:
        return handler(db, event)
    except IntegrityError as exc:
        db.rollback()
        if _event_already_processed(db, event_id=event.event_id):
            return PaymentWebhookAck(
                processed=False,
                event_id=event.event_id,
                event_type=event.event_type,
                duplicate=True,
                message="duplicate_event",
            )
        raise PaymentServiceError(
            "Conflitto idempotenza durante la lavorazione webhook.",
            status_code=409,
        ) from exc
    except PaymentServiceError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def _handle_checkout_session_completed(db: Session, event: ProviderWebhookEvent) -> PaymentWebhookAck:
    payload = event.object_payload
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    user_id = _safe_int(metadata.get("app_user_id"))
    if user_id is None:
        raise PaymentServiceError(
            "Webhook checkout.session.completed senza app_user_id.",
            status_code=400,
        )

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise PaymentServiceError("Utente webhook non trovato.", status_code=404)

    plan_code = _normalize_text(metadata.get("plan_code"), 32) or PLAN_PRO
    billing_cycle = _normalize_billing_cycle(metadata.get("billing_cycle")) or BILLING_CYCLE_MONTHLY
    period_days = _period_days_for_cycle(billing_cycle)

    customer_external_id = _normalize_text(payload.get("customer"), 191)
    customer = None
    if customer_external_id is not None:
        customer = _upsert_customer_mapping(
            db,
            user=user,
            provider_name=PAYMENT_PROVIDER_STRIPE,
            provider_customer_id=customer_external_id,
            at=event.created_at,
        )

    try:
        created = create_subscription(
            db,
            user_id=user.id,
            plan_code=plan_code,
            started_at=event.created_at,
            trial_days=0,
            period_days=period_days,
            now=event.created_at,
            provider=PAYMENT_PROVIDER_STRIPE,
            provider_event_id=event.event_id,
            commit=False,
        )
    except SubscriptionError as exc:
        raise PaymentServiceError(exc.message, status_code=exc.status_code) from exc

    subscription = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(Subscription.id == created.id)
    ).unique().scalar_one()

    session_id = _normalize_text(payload.get("id"), 191)
    provider_subscription_id = _normalize_text(payload.get("subscription"), 191)
    if session_id:
        checkout_row = db.scalar(
            select(PaymentCheckoutSession).where(
                PaymentCheckoutSession.provider == PAYMENT_PROVIDER_STRIPE,
                PaymentCheckoutSession.provider_session_id == session_id,
            )
        )
        if checkout_row is not None:
            checkout_row.status = "completed"
            checkout_row.customer_id = customer.id if customer is not None else checkout_row.customer_id
            checkout_row.provider_subscription_id = provider_subscription_id
            checkout_row.completed_at = event.created_at
            checkout_row.raw_payload_json = _serialize_payload(event.raw_payload)
            checkout_row.updated_at = event.created_at

    payment_event = db.scalar(
        select(PaymentEvent).where(
            PaymentEvent.provider == PAYMENT_PROVIDER_STRIPE,
            PaymentEvent.provider_event_id == event.event_id,
        )
    )
    if payment_event is not None:
        payment_event.amount_cents = _safe_int(payload.get("amount_total"))
        payment_event.currency = _normalize_text(payload.get("currency"), 8)
        payment_event.raw_payload_json = _serialize_payload(event.raw_payload)

    db.commit()
    return PaymentWebhookAck(
        processed=True,
        event_id=event.event_id,
        event_type=event.event_type,
        message=f"subscription_created:{subscription.id}",
    )


def _handle_invoice_payment_succeeded(db: Session, event: ProviderWebhookEvent) -> PaymentWebhookAck:
    payload = event.object_payload
    billing_reason = _normalize_text(payload.get("billing_reason"), 64)
    if billing_reason != "subscription_cycle":
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="ignored_billing_reason",
        )

    customer_external_id = _normalize_text(payload.get("customer"), 191)
    if customer_external_id is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="missing_customer",
        )

    customer = db.scalar(
        select(PaymentCustomer).where(
            PaymentCustomer.provider == PAYMENT_PROVIDER_STRIPE,
            PaymentCustomer.provider_customer_id == customer_external_id,
        )
    )
    if customer is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="customer_not_mapped",
        )

    subscription = _find_latest_subscription_for_user(db, user_id=customer.user_id)
    if subscription is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="subscription_not_found",
        )

    default_period_days = max(1, int((subscription.plan.billing_period_days if subscription.plan else 30) or 30))
    period_days = _period_days_from_invoice(payload, fallback_days=default_period_days)

    try:
        renewed = renew_subscription(
            db,
            subscription.id,
            period_days=period_days,
            now=event.created_at,
            provider=PAYMENT_PROVIDER_STRIPE,
            provider_event_id=event.event_id,
            amount_cents=_safe_int(payload.get("amount_paid")) or _safe_int(payload.get("total")),
            currency=_normalize_text(payload.get("currency"), 8),
            commit=False,
        )
    except SubscriptionError as exc:
        raise PaymentServiceError(exc.message, status_code=exc.status_code) from exc

    payment_event = db.scalar(
        select(PaymentEvent).where(
            PaymentEvent.provider == PAYMENT_PROVIDER_STRIPE,
            PaymentEvent.provider_event_id == event.event_id,
        )
    )
    if payment_event is not None:
        payment_event.raw_payload_json = _serialize_payload(event.raw_payload)

    db.commit()

    return PaymentWebhookAck(
        processed=True,
        event_id=event.event_id,
        event_type=event.event_type,
        message=f"subscription_renewed:{renewed.id}",
    )


def _handle_invoice_payment_failed(db: Session, event: ProviderWebhookEvent) -> PaymentWebhookAck:
    payload = event.object_payload
    customer_external_id = _normalize_text(payload.get("customer"), 191)
    if customer_external_id is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="missing_customer",
        )

    customer = db.scalar(
        select(PaymentCustomer).where(
            PaymentCustomer.provider == PAYMENT_PROVIDER_STRIPE,
            PaymentCustomer.provider_customer_id == customer_external_id,
        )
    )
    if customer is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="customer_not_mapped",
        )

    subscription = _find_latest_subscription_for_user(db, user_id=customer.user_id)
    if subscription is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="subscription_not_found",
        )

    _record_provider_payment_event(
        db,
        subscription=subscription,
        event=event,
        event_type="invoice_payment_failed",
        status="failed",
        amount_cents=_safe_int(payload.get("amount_due")) or _safe_int(payload.get("total")),
        currency=_normalize_text(payload.get("currency"), 8),
    )
    db.commit()
    return PaymentWebhookAck(
        processed=True,
        event_id=event.event_id,
        event_type=event.event_type,
        message=f"payment_failed:{subscription.id}",
    )


def _handle_subscription_deleted(db: Session, event: ProviderWebhookEvent) -> PaymentWebhookAck:
    payload = event.object_payload
    customer_external_id = _normalize_text(payload.get("customer"), 191)
    if customer_external_id is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="missing_customer",
        )

    customer = db.scalar(
        select(PaymentCustomer).where(
            PaymentCustomer.provider == PAYMENT_PROVIDER_STRIPE,
            PaymentCustomer.provider_customer_id == customer_external_id,
        )
    )
    if customer is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="customer_not_mapped",
        )

    subscription = _find_latest_subscription_for_user(db, user_id=customer.user_id)
    if subscription is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="subscription_not_found",
        )

    if subscription.status not in {"canceled", "expired"}:
        try:
            cancel_subscription(
                db,
                subscription.id,
                immediate=True,
                reason="provider_subscription_deleted",
                now=event.created_at,
                commit=False,
            )
        except SubscriptionError as exc:
            raise PaymentServiceError(exc.message, status_code=exc.status_code) from exc
        subscription = db.execute(
            select(Subscription)
            .options(joinedload(Subscription.plan))
            .where(Subscription.id == subscription.id)
        ).unique().scalar_one()

    provider_subscription_id = _normalize_text(payload.get("id"), 191)
    if provider_subscription_id:
        _upsert_checkout_subscription_link(
            db,
            customer_id=customer.id,
            provider_subscription_id=provider_subscription_id,
            status="canceled",
            at=event.created_at,
            raw_payload=event.raw_payload,
        )

    _record_provider_payment_event(
        db,
        subscription=subscription,
        event=event,
        event_type="subscription_deleted",
        status="succeeded",
        amount_cents=None,
        currency=_normalize_text(payload.get("currency"), 8) or (subscription.plan.currency if subscription.plan else None),
    )
    db.commit()
    return PaymentWebhookAck(
        processed=True,
        event_id=event.event_id,
        event_type=event.event_type,
        message=f"subscription_deleted:{subscription.id}",
    )


def _handle_subscription_updated(db: Session, event: ProviderWebhookEvent) -> PaymentWebhookAck:
    payload = event.object_payload
    customer_external_id = _normalize_text(payload.get("customer"), 191)
    if customer_external_id is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="missing_customer",
        )

    customer = _find_payment_customer(db, customer_external_id=customer_external_id)
    if customer is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="customer_not_mapped",
        )

    subscription = _find_latest_subscription_for_user(db, user_id=customer.user_id)
    if subscription is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="subscription_not_found",
        )

    provider_subscription_id = _normalize_text(payload.get("id"), 191)
    stripe_status = _normalize_text(payload.get("status"), 64)
    mapped_status = _map_stripe_subscription_status(stripe_status)
    cancel_at_period_end = _safe_bool(payload.get("cancel_at_period_end"))
    current_period_start_at = _safe_epoch_to_naive_utc(payload.get("current_period_start"))
    current_period_end_at = _safe_epoch_to_naive_utc(payload.get("current_period_end"))
    canceled_at = _safe_epoch_to_naive_utc(payload.get("canceled_at"))

    if current_period_start_at is not None:
        subscription.current_period_start_at = current_period_start_at
    if current_period_end_at is not None:
        subscription.current_period_end_at = current_period_end_at
        subscription.expires_at = current_period_end_at

    if canceled_at is not None:
        subscription.canceled_at = canceled_at

    if cancel_at_period_end is not None:
        subscription.cancel_at_period_end = cancel_at_period_end
        if cancel_at_period_end:
            subscription.auto_renew = False

    if mapped_status == "canceled":
        effective_canceled_at = canceled_at or current_period_end_at or event.created_at
        subscription.status = "canceled"
        subscription.canceled_at = effective_canceled_at
        subscription.current_period_end_at = subscription.current_period_end_at or effective_canceled_at
        subscription.expires_at = subscription.current_period_end_at or effective_canceled_at
        subscription.auto_renew = False
        subscription.cancel_at_period_end = False
    elif mapped_status == "suspended":
        subscription.status = "suspended"
        subscription.suspended_at = event.created_at
        subscription.suspension_reason = _normalize_text(
            f"provider_status:{stripe_status or 'unknown'}",
            255,
        )
        subscription.auto_renew = False
    elif mapped_status in {"active", "trialing"}:
        subscription.status = mapped_status
        subscription.suspended_at = None
        subscription.suspension_reason = None
        if cancel_at_period_end is False:
            subscription.auto_renew = True

    subscription.updated_at = event.created_at

    if provider_subscription_id:
        checkout_status = "canceled" if mapped_status == "canceled" else None
        _upsert_checkout_subscription_link(
            db,
            customer_id=customer.id,
            provider_subscription_id=provider_subscription_id,
            status=checkout_status,
            at=event.created_at,
            raw_payload=event.raw_payload,
        )

    _record_provider_payment_event(
        db,
        subscription=subscription,
        event=event,
        event_type="subscription_updated",
        status="succeeded",
        amount_cents=None,
        currency=_normalize_text(payload.get("currency"), 8) or (subscription.plan.currency if subscription.plan else None),
    )
    db.commit()
    return PaymentWebhookAck(
        processed=True,
        event_id=event.event_id,
        event_type=event.event_type,
        message=f"subscription_updated:{subscription.id}",
    )


def _handle_charge_refunded(db: Session, event: ProviderWebhookEvent) -> PaymentWebhookAck:
    payload = event.object_payload
    customer_external_id = _normalize_text(payload.get("customer"), 191)
    if customer_external_id is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="missing_customer",
        )

    customer = _find_payment_customer(db, customer_external_id=customer_external_id)
    if customer is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="customer_not_mapped",
        )

    subscription = _find_latest_subscription_for_user(db, user_id=customer.user_id)
    if subscription is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="subscription_not_found",
        )

    provider_status = (_normalize_text(payload.get("status"), 32) or "succeeded").lower()
    event_status = "succeeded"
    if provider_status in {"failed", "canceled"}:
        event_status = "failed"
    elif provider_status in {"pending", "requires_action"}:
        event_status = "pending"

    _record_provider_payment_event(
        db,
        subscription=subscription,
        event=event,
        event_type="charge_refunded",
        status=event_status,
        amount_cents=_safe_int(payload.get("amount_refunded")) or _safe_int(payload.get("amount")),
        currency=_normalize_text(payload.get("currency"), 8) or (subscription.plan.currency if subscription.plan else None),
    )
    db.commit()
    return PaymentWebhookAck(
        processed=True,
        event_id=event.event_id,
        event_type=event.event_type,
        message=f"charge_refunded:{subscription.id}",
    )


def _handle_charge_dispute_created(db: Session, event: ProviderWebhookEvent) -> PaymentWebhookAck:
    payload = event.object_payload
    customer_external_id = _normalize_text(payload.get("customer"), 191)
    if customer_external_id is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="missing_customer",
        )

    customer = _find_payment_customer(db, customer_external_id=customer_external_id)
    if customer is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="customer_not_mapped",
        )

    subscription = _find_latest_subscription_for_user(db, user_id=customer.user_id)
    if subscription is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="subscription_not_found",
        )

    if subscription.status not in {"canceled", "expired"}:
        dispute_reason = _normalize_text(payload.get("reason"), 128) or "unknown"
        subscription.status = "suspended"
        subscription.suspended_at = event.created_at
        subscription.suspension_reason = _normalize_text(f"charge_dispute:{dispute_reason}", 255)
        subscription.auto_renew = False
        subscription.updated_at = event.created_at

    _record_provider_payment_event(
        db,
        subscription=subscription,
        event=event,
        event_type="charge_dispute_created",
        status="pending",
        amount_cents=_safe_int(payload.get("amount")),
        currency=_normalize_text(payload.get("currency"), 8) or (subscription.plan.currency if subscription.plan else None),
    )
    db.commit()
    return PaymentWebhookAck(
        processed=True,
        event_id=event.event_id,
        event_type=event.event_type,
        message=f"charge_dispute_created:{subscription.id}",
    )


def _handle_charge_dispute_updated(db: Session, event: ProviderWebhookEvent) -> PaymentWebhookAck:
    return _handle_charge_dispute_state_change(db, event, event_type="charge_dispute_updated")


def _handle_charge_dispute_closed(db: Session, event: ProviderWebhookEvent) -> PaymentWebhookAck:
    return _handle_charge_dispute_state_change(db, event, event_type="charge_dispute_closed")


def _handle_charge_dispute_state_change(
    db: Session,
    event: ProviderWebhookEvent,
    *,
    event_type: str,
) -> PaymentWebhookAck:
    payload = event.object_payload
    customer_external_id = _normalize_text(payload.get("customer"), 191)
    if customer_external_id is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="missing_customer",
        )

    customer = _find_payment_customer(db, customer_external_id=customer_external_id)
    if customer is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="customer_not_mapped",
        )

    subscription = _find_latest_subscription_for_user(db, user_id=customer.user_id)
    if subscription is None:
        return PaymentWebhookAck(
            processed=False,
            event_id=event.event_id,
            event_type=event.event_type,
            message="subscription_not_found",
        )

    dispute_status = (_normalize_text(payload.get("status"), 64) or "").lower()
    event_status = "pending"

    if dispute_status in {"won", "warning_closed"}:
        event_status = "succeeded"
        if subscription.status == "suspended":
            if subscription.expires_at is not None and subscription.expires_at <= event.created_at:
                subscription.status = "expired"
            elif subscription.trial_ends_at is not None and subscription.trial_ends_at > event.created_at:
                subscription.status = "trialing"
            else:
                subscription.status = "active"
        subscription.suspended_at = None
        subscription.suspension_reason = None
        if subscription.status in {"active", "trialing"}:
            subscription.auto_renew = not bool(subscription.cancel_at_period_end)
        subscription.updated_at = event.created_at
    elif dispute_status == "lost":
        event_status = "failed"
        if subscription.status not in {"canceled", "expired"}:
            subscription.status = "suspended"
            subscription.suspended_at = subscription.suspended_at or event.created_at
            subscription.suspension_reason = "charge_dispute_lost"
            subscription.auto_renew = False
            subscription.updated_at = event.created_at
    elif subscription.status not in {"canceled", "expired"}:
        subscription.status = "suspended"
        subscription.suspended_at = subscription.suspended_at or event.created_at
        subscription.suspension_reason = _normalize_text(
            f"charge_dispute:{dispute_status or 'open'}",
            255,
        )
        subscription.auto_renew = False
        subscription.updated_at = event.created_at

    _record_provider_payment_event(
        db,
        subscription=subscription,
        event=event,
        event_type=event_type,
        status=event_status,
        amount_cents=_safe_int(payload.get("amount")),
        currency=_normalize_text(payload.get("currency"), 8) or (subscription.plan.currency if subscription.plan else None),
    )
    db.commit()
    return PaymentWebhookAck(
        processed=True,
        event_id=event.event_id,
        event_type=event.event_type,
        message=f"{event_type}:{subscription.id}",
    )


_WEBHOOK_HANDLERS: dict[str, Any] = {
    "checkout.session.completed": _handle_checkout_session_completed,
    "customer.subscription.updated": _handle_subscription_updated,
    "invoice.payment_succeeded": _handle_invoice_payment_succeeded,
    "invoice.payment_failed": _handle_invoice_payment_failed,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "charge.refunded": _handle_charge_refunded,
    "charge.dispute.created": _handle_charge_dispute_created,
    "charge.dispute.updated": _handle_charge_dispute_updated,
    "charge.dispute.closed": _handle_charge_dispute_closed,
    "charge.dispute.funds_withdrawn": _handle_charge_dispute_updated,
    "charge.dispute.funds_reinstated": _handle_charge_dispute_updated,
}


def _resolve_provider(
    *,
    settings: Settings,
    provider_override: PaymentProvider | None,
    expected_provider_name: str | None,
) -> PaymentProvider:
    provider_name = _normalize_text(settings.payments_provider, 64)
    if provider_name is None:
        raise PaymentServiceError(
            "Pagamenti non configurati: PAYMENTS_PROVIDER mancante.",
            status_code=503,
        )
    provider_name = provider_name.lower()

    if provider_override is not None:
        if provider_override.provider_name != provider_name:
            raise PaymentServiceError(
                "Provider override non coerente con PAYMENTS_PROVIDER.",
                status_code=500,
            )
        if expected_provider_name and provider_override.provider_name != expected_provider_name:
            raise PaymentServiceError(
                f"Webhook supportato solo per provider {expected_provider_name}.",
                status_code=400,
            )
        return provider_override

    if provider_name == PAYMENT_PROVIDER_STRIPE:
        if expected_provider_name and expected_provider_name != PAYMENT_PROVIDER_STRIPE:
            raise PaymentServiceError("Provider webhook non supportato.", status_code=400)
        return StripePaymentProvider(settings)

    raise PaymentServiceError(
        f"Provider pagamenti non supportato: {provider_name}.",
        status_code=400,
    )


def _ensure_provider_customer(
    db: Session,
    *,
    user: User,
    provider: PaymentProvider,
    resolved_now: datetime,
) -> PaymentCustomer:
    existing = db.scalar(
        select(PaymentCustomer).where(
            PaymentCustomer.user_id == user.id,
            PaymentCustomer.provider == provider.provider_name,
        )
    )
    if existing is not None:
        return existing

    try:
        provider_customer = provider.create_customer(
            external_user_id=str(user.id),
            telegram_user_id=user.telegram_user_id,
            username=user.username,
            email=None,
            metadata={
                "app_user_id": str(user.id),
                "telegram_user_id": str(user.telegram_user_id or ""),
            },
        )
    except PaymentProviderError as exc:
        raise PaymentServiceError(exc.message, status_code=exc.status_code) from exc

    row = PaymentCustomer(
        user_id=user.id,
        provider=provider.provider_name,
        provider_customer_id=provider_customer.customer_id,
        status="active",
        created_at=resolved_now,
        updated_at=resolved_now,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        deduped = db.scalar(
            select(PaymentCustomer).where(
                PaymentCustomer.user_id == user.id,
                PaymentCustomer.provider == provider.provider_name,
            )
        )
        if deduped is not None:
            return deduped
        raise PaymentServiceError(
            "Conflitto durante la creazione customer provider.",
            status_code=409,
        ) from exc
    return row


def _upsert_customer_mapping(
    db: Session,
    *,
    user: User,
    provider_name: str,
    provider_customer_id: str,
    at: datetime,
) -> PaymentCustomer:
    row = db.scalar(
        select(PaymentCustomer).where(
            PaymentCustomer.user_id == user.id,
            PaymentCustomer.provider == provider_name,
        )
    )
    if row is None:
        row = PaymentCustomer(
            user_id=user.id,
            provider=provider_name,
            provider_customer_id=provider_customer_id,
            status="active",
            created_at=at,
            updated_at=at,
        )
        db.add(row)
        db.flush()
        return row

    if row.provider_customer_id != provider_customer_id:
        row.provider_customer_id = provider_customer_id
        row.updated_at = at
        db.flush()
    return row


def _resolve_checkout_urls(
    *,
    settings: Settings,
    success_url: str | None,
    cancel_url: str | None,
) -> tuple[str, str]:
    resolved_success_url = _normalize_text(success_url, 1024) or _normalize_text(
        settings.payments_success_url,
        1024,
    )
    resolved_cancel_url = _normalize_text(cancel_url, 1024) or _normalize_text(
        settings.payments_cancel_url,
        1024,
    )
    if resolved_success_url is None or resolved_cancel_url is None:
        raise PaymentServiceError(
            "Payments success/cancel URL non configurate.",
            status_code=500,
        )
    return resolved_success_url, resolved_cancel_url


def _resolve_portal_return_url(*, settings: Settings, return_url: str | None) -> str:
    resolved_return_url = _normalize_text(return_url, 1024)
    if resolved_return_url is None:
        resolved_return_url = _normalize_text(settings.payments_portal_return_url, 1024)
    if resolved_return_url is None:
        resolved_return_url = _normalize_text(settings.payments_success_url, 1024)
    if resolved_return_url is None:
        raise PaymentServiceError(
            "URL di ritorno del portale non configurato.",
            status_code=500,
        )
    return resolved_return_url


def _resolve_portal_ttl_seconds(settings: Settings) -> int:
    try:
        configured = int(settings.payments_portal_link_ttl_seconds)
    except (TypeError, ValueError):
        configured = 1800
    # Keep portal links short-lived and avoid accidental extreme values.
    return max(300, min(configured, 86400))


def _resolve_portal_idempotency_key(
    *,
    idempotency_key: str | None,
    user_id: int,
    provider_name: str,
    now: datetime,
    settings: Settings,
) -> str:
    cleaned = _normalize_text(idempotency_key, 128)
    if cleaned is not None:
        return cleaned

    bucket = _resolve_portal_ttl_seconds(settings)
    epoch_bucket = int(now.replace(tzinfo=timezone.utc).timestamp()) // bucket
    raw = f"portal:{provider_name}:{user_id}:{epoch_bucket}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"portal_{digest[:60]}"


def _resolve_idempotency_key(
    *,
    idempotency_key: str | None,
    user_id: int,
    plan_code: str,
    billing_cycle: str,
    now: datetime,
    settings: Settings,
) -> str:
    cleaned = _normalize_text(idempotency_key, 128)
    if cleaned is not None:
        return cleaned

    bucket = max(60, int(settings.payments_idempotency_bucket_seconds))
    epoch_bucket = int(now.replace(tzinfo=timezone.utc).timestamp()) // bucket
    raw = f"{user_id}:{plan_code}:{billing_cycle}:{epoch_bucket}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"chk_{digest[:60]}"


def _resolve_price_id_for_cycle(settings: Settings, billing_cycle: str) -> str:
    if billing_cycle == BILLING_CYCLE_MONTHLY:
        price_id = _normalize_text(settings.stripe_price_monthly, 191)
        if price_id is None:
            raise PaymentServiceError(
                "STRIPE_PRICE_MONTHLY non configurato.",
                status_code=500,
            )
        return price_id

    if billing_cycle == BILLING_CYCLE_YEARLY:
        price_id = _normalize_text(settings.stripe_price_yearly, 191)
        if price_id is None:
            raise PaymentServiceError(
                "STRIPE_PRICE_YEARLY non configurato.",
                status_code=400,
            )
        return price_id

    raise PaymentServiceError("billing_cycle non supportato.", status_code=400)


def _period_days_for_cycle(billing_cycle: str) -> int:
    if billing_cycle == BILLING_CYCLE_YEARLY:
        return 365
    return 30


def _event_already_processed(db: Session, *, event_id: str) -> bool:
    row = db.scalar(
        select(PaymentEvent).where(
            PaymentEvent.provider == PAYMENT_PROVIDER_STRIPE,
            PaymentEvent.provider_event_id == event_id,
        )
    )
    return row is not None


def _find_latest_subscription_for_user(db: Session, *, user_id: int) -> Subscription | None:
    rows = db.execute(
        select(Subscription)
        .options(joinedload(Subscription.plan))
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.started_at.desc(), Subscription.id.desc())
    ).unique().scalars().all()
    if not rows:
        return None
    for row in rows:
        if row.status in _OPEN_SUBSCRIPTION_STATUSES:
            return row
    return rows[0]


def _record_provider_payment_event(
    db: Session,
    *,
    subscription: Subscription,
    event: ProviderWebhookEvent,
    event_type: str,
    status: str,
    amount_cents: int | None,
    currency: str | None,
) -> None:
    db.add(
        PaymentEvent(
            subscription_id=subscription.id,
            user_id=subscription.user_id,
            provider=PAYMENT_PROVIDER_STRIPE,
            provider_event_id=event.event_id,
            event_type=event_type,
            status=status,
            amount_cents=amount_cents,
            currency=currency,
            event_at=event.created_at,
            raw_payload_json=_serialize_payload(event.raw_payload),
            created_at=event.created_at,
        )
    )


def _find_payment_customer(db: Session, *, customer_external_id: str) -> PaymentCustomer | None:
    return db.scalar(
        select(PaymentCustomer).where(
            PaymentCustomer.provider == PAYMENT_PROVIDER_STRIPE,
            PaymentCustomer.provider_customer_id == customer_external_id,
        )
    )


def _upsert_checkout_subscription_link(
    db: Session,
    *,
    customer_id: int,
    provider_subscription_id: str,
    status: str | None,
    at: datetime,
    raw_payload: dict[str, Any],
) -> None:
    rows = db.scalars(
        select(PaymentCheckoutSession)
        .where(
            PaymentCheckoutSession.provider == PAYMENT_PROVIDER_STRIPE,
            PaymentCheckoutSession.customer_id == customer_id,
        )
        .order_by(PaymentCheckoutSession.created_at.desc(), PaymentCheckoutSession.id.desc())
    ).all()
    if not rows:
        return

    target: PaymentCheckoutSession | None = None
    for row in rows:
        if row.provider_subscription_id == provider_subscription_id:
            target = row
            break
    if target is None:
        for row in rows:
            if row.provider_subscription_id is None:
                target = row
                break
    if target is None:
        return

    target.provider_subscription_id = provider_subscription_id
    if status is not None:
        target.status = status
        if status == "canceled":
            target.canceled_at = at
    target.raw_payload_json = _serialize_payload(raw_payload)
    target.updated_at = at


def _map_stripe_subscription_status(value: str | None) -> str | None:
    normalized = _normalize_text(value, 64)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if lowered == "active":
        return "active"
    if lowered == "trialing":
        return "trialing"
    if lowered in _STRIPE_SUSPENDED_STATUSES:
        return "suspended"
    if lowered in _STRIPE_CANCELED_STATUSES:
        return "canceled"
    return None


def _safe_epoch_to_naive_utc(value: Any) -> datetime | None:
    timestamp = _safe_int(value)
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _safe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _period_days_from_invoice(payload: dict[str, Any], *, fallback_days: int) -> int:
    lines_section = payload.get("lines")
    if isinstance(lines_section, dict):
        rows = lines_section.get("data")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                period = row.get("period")
                if not isinstance(period, dict):
                    continue
                start = _safe_int(period.get("start"))
                end = _safe_int(period.get("end"))
                if start is None or end is None or end <= start:
                    continue
                seconds = end - start
                days = max(1, int(round(seconds / 86400)))
                return days
    return max(1, int(fallback_days))


def _checkout_read(row: PaymentCheckoutSession, *, mode: str | None, reused: bool) -> PaymentCheckoutRead:
    if row.customer is None:
        raise PaymentServiceError(
            "Checkout salvata senza customer provider associato.",
            status_code=500,
        )
    if not row.provider_session_id or not row.checkout_url:
        raise PaymentServiceError(
            "Checkout salvata senza sessione provider valida.",
            status_code=500,
        )

    return PaymentCheckoutRead(
        provider=row.provider,
        mode=(mode or "sandbox"),
        idempotency_key=row.idempotency_key,
        checkout_url=row.checkout_url,
        session_id=row.provider_session_id,
        customer_id=row.customer.provider_customer_id,
        plan_code=row.plan_code,
        billing_cycle=row.billing_cycle,
        expires_at=row.expires_at,
        reused=reused,
    )


def _normalize_billing_cycle(value: str | None) -> str | None:
    cleaned = _normalize_text(value, 16)
    if cleaned is None:
        return None
    normalized = cleaned.lower()
    if normalized not in _SUPPORTED_BILLING_CYCLES:
        return None
    return normalized


def _serialize_payload(payload: dict[str, Any]) -> str:
    safe_payload = _safe_payment_payload(payload)
    try:
        return json.dumps(safe_payload, ensure_ascii=True, sort_keys=True)
    except TypeError:
        fallback = {str(key): str(value) for key, value in safe_payload.items()}
        return json.dumps(fallback, ensure_ascii=True, sort_keys=True)


def _safe_payment_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Store only a strict provider payload subset (no card/payment method data)."""

    if not isinstance(payload, dict):
        return {}

    object_payload: dict[str, Any] = payload
    data_section = payload.get("data")
    if isinstance(data_section, dict) and isinstance(data_section.get("object"), dict):
        object_payload = data_section["object"]

    safe_object: dict[str, Any] = {}
    for key in (
        "id",
        "object",
        "customer",
        "subscription",
        "status",
        "currency",
        "amount_total",
        "amount_paid",
        "amount_due",
        "amount",
        "amount_refunded",
        "billing_reason",
        "charge",
        "invoice",
        "payment_intent",
        "reason",
        "cancel_at_period_end",
        "current_period_start",
        "current_period_end",
        "canceled_at",
        "mode",
        "livemode",
        "expires_at",
        "url",
        "client_reference_id",
        "metadata",
    ):
        value = object_payload.get(key)
        if value is None:
            continue
        if key == "metadata" and isinstance(value, dict):
            safe_object[key] = {
                str(meta_key): str(meta_value)
                for meta_key, meta_value in value.items()
            }
        else:
            safe_object[key] = value

    # Keep only period boundaries used for renewal calculations.
    lines_section = object_payload.get("lines")
    if isinstance(lines_section, dict):
        rows = lines_section.get("data")
        if isinstance(rows, list):
            periods: list[dict[str, int]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                period = row.get("period")
                if not isinstance(period, dict):
                    continue
                start = _safe_int(period.get("start"))
                end = _safe_int(period.get("end"))
                if start is None or end is None:
                    continue
                periods.append({"start": start, "end": end})
            if periods:
                safe_object["line_periods"] = periods

    safe_top_level: dict[str, Any] = {}
    for key in ("id", "type", "created", "livemode"):
        value = payload.get(key)
        if value is not None:
            safe_top_level[key] = value

    if safe_top_level:
        safe_top_level["object"] = safe_object
        return safe_top_level
    return safe_object


def _normalize_text(value: Any, max_len: int) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)








