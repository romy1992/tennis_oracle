"""Admin subscriptions dashboard service layer (SUB-06)."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import io
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.src.app.schemas.subscription_dashboard import (
    SubscriptionDashboardEventListResponse,
    SubscriptionDashboardEventRow,
    SubscriptionDashboardOverview,
    SubscriptionDashboardRevenuePoint,
    SubscriptionDashboardSummaryResponse,
    SubscriptionDashboardUserListResponse,
    SubscriptionDashboardUserRow,
)
from backend.src.app.schemas.subscriptions import SubscriptionRead
from backend.src.app.services.subscriptions import (
    PLAN_FOUNDER,
    PLAN_FREE,
    PLAN_PRO,
    SUB_STATUS_ACTIVE,
    SUB_STATUS_CANCELED,
    SUB_STATUS_EXPIRED,
    SUB_STATUS_SUSPENDED,
    SUB_STATUS_TRIALING,
    SubscriptionError,
    cancel_subscription,
    resume_subscription,
    seed_default_plans,
    suspend_subscription,
)
from backend.src.entity.admin_audit_log import AdminAuditLog
from backend.src.entity.admin_user import AdminUser
from backend.src.entity.subscription import PaymentEvent, Subscription, User

_OPEN_STATUSES = frozenset({SUB_STATUS_ACTIVE, SUB_STATUS_TRIALING, SUB_STATUS_SUSPENDED})


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_text(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _serialize_context(context: dict[str, Any] | None) -> str | None:
    if not context:
        return None
    try:
        return json.dumps(context, ensure_ascii=True, sort_keys=True)
    except TypeError:
        fallback = {str(key): str(value) for key, value in context.items()}
        return json.dumps(fallback, ensure_ascii=True, sort_keys=True)


def _parse_context(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _latest_key(dt_value: datetime | None, row_id: int | None) -> tuple[datetime, int]:
    return (dt_value or datetime.min, row_id or 0)


def _resolve_current_or_latest_subscription(user: User, *, at: datetime) -> Subscription | None:
    if not user.subscriptions:
        return None

    ordered = sorted(
        user.subscriptions,
        key=lambda row: _latest_key(row.started_at, row.id),
    )
    active_candidates: list[Subscription] = []
    for row in ordered:
        if row.started_at is not None and row.started_at > at:
            continue
        if row.status not in _OPEN_STATUSES:
            continue
        if row.expires_at is not None and row.expires_at <= at:
            continue
        active_candidates.append(row)

    if active_candidates:
        return active_candidates[-1]
    return ordered[-1]


def _list_users_with_context(db: Session) -> list[User]:
    return (
        db.execute(
            select(User)
            .options(
                joinedload(User.subscriptions).joinedload(Subscription.plan),
                joinedload(User.payment_events),
            )
            .order_by(User.id.asc())
        )
        .unique()
        .scalars()
        .all()
    )


def _matches_search(user: User, q: str | None) -> bool:
    cleaned = _normalize_text(q, 255)
    if cleaned is None:
        return True
    needle = cleaned.lower()
    values = [
        user.username or "",
        user.external_ref or "",
        str(user.telegram_user_id) if user.telegram_user_id is not None else "",
    ]
    haystack = " ".join(values).lower()
    return needle in haystack


def _latest_payment_for_subscription(
    user: User,
    subscription_id: int | None,
) -> PaymentEvent | None:
    rows = user.payment_events
    if subscription_id is not None:
        rows = [row for row in rows if row.subscription_id == subscription_id]
    if not rows:
        return None
    return max(rows, key=lambda row: _latest_key(row.event_at, row.id))


def _has_failed_payment(user: User, subscription_id: int | None) -> bool:
    rows = user.payment_events
    if subscription_id is not None:
        rows = [row for row in rows if row.subscription_id == subscription_id]
    return any((row.status or "").lower() == "failed" for row in rows)


def _is_subscription_active_at(subscription: Subscription, at: datetime) -> bool:
    if subscription.started_at is not None and subscription.started_at > at:
        return False
    if subscription.canceled_at is not None and subscription.canceled_at <= at:
        return False
    if subscription.expires_at is not None and subscription.expires_at <= at:
        return False
    return True


def _subscription_ended_at(subscription: Subscription, *, now: datetime) -> datetime | None:
    if subscription.canceled_at is not None:
        return subscription.canceled_at
    if subscription.expires_at is not None and subscription.expires_at <= now:
        return subscription.expires_at
    return None


def _pct(part: int, whole: int) -> float | None:
    if whole <= 0:
        return None
    return round((part / whole) * 100.0, 2)


def _month_start(value: datetime) -> datetime:
    return datetime(value.year, value.month, 1)


def _shift_month(value: datetime, delta_months: int) -> datetime:
    month = value.month - 1 + delta_months
    year = value.year + month // 12
    month = month % 12 + 1
    return datetime(year, month, 1)


def _month_labels(now: datetime, months: int) -> list[str]:
    total = max(1, int(months))
    start = _month_start(now)
    labels: list[str] = []
    for offset in range(total - 1, -1, -1):
        labels.append(_shift_month(start, -offset).strftime("%Y-%m"))
    return labels


def get_subscription_dashboard_summary(
    db: Session,
    *,
    months: int = 6,
    now: datetime | None = None,
) -> SubscriptionDashboardSummaryResponse:
    """Aggregate dashboard KPIs: plans, lifecycle, conversion, churn, revenue."""

    seed_default_plans(db, commit=False)
    resolved_now = now or _utc_now_naive()
    users = _list_users_with_context(db)

    users_by_plan = {PLAN_FREE: 0, PLAN_PRO: 0, PLAN_FOUNDER: 0}
    all_subscriptions: list[Subscription] = []
    all_events: list[PaymentEvent] = []

    free_user_base = 0
    free_to_pro_users = 0

    for user in users:
        current = _resolve_current_or_latest_subscription(user, at=resolved_now)
        if current is not None and current.plan is not None:
            code = (current.plan.code or "").lower()
            if code in users_by_plan:
                users_by_plan[code] += 1

        ordered_subscriptions = sorted(
            user.subscriptions,
            key=lambda row: _latest_key(row.started_at, row.id),
        )
        all_subscriptions.extend(ordered_subscriptions)
        all_events.extend(user.payment_events)

        has_free = False
        converted_to_pro = False
        for row in ordered_subscriptions:
            code = (row.plan.code if row.plan is not None else "").lower()
            if code == PLAN_FREE:
                has_free = True
            if has_free and code == PLAN_PRO:
                converted_to_pro = True
                break
        if has_free:
            free_user_base += 1
            if converted_to_pro:
                free_to_pro_users += 1

    window_start = resolved_now - timedelta(days=30)
    active_base_user_ids: set[int] = set()
    churned_user_ids: set[int] = set()

    active_subscriptions = 0
    trialing_subscriptions = 0
    canceled_subscriptions = 0
    canceled_last_30_days = 0
    expiring_within_7_days = 0
    expiring_within_30_days = 0

    for row in all_subscriptions:
        if row.status == SUB_STATUS_ACTIVE:
            active_subscriptions += 1
        if row.status == SUB_STATUS_TRIALING:
            trialing_subscriptions += 1
        if row.status == SUB_STATUS_CANCELED:
            canceled_subscriptions += 1

        if row.canceled_at is not None and row.canceled_at >= window_start:
            canceled_last_30_days += 1

        if row.expires_at is not None and row.expires_at >= resolved_now:
            if row.expires_at <= resolved_now + timedelta(days=30):
                expiring_within_30_days += 1
            if row.expires_at <= resolved_now + timedelta(days=7):
                expiring_within_7_days += 1

        if row.user_id is not None and _is_subscription_active_at(row, window_start):
            active_base_user_ids.add(int(row.user_id))

        ended_at = _subscription_ended_at(row, now=resolved_now)
        if ended_at is not None and window_start <= ended_at <= resolved_now:
            churned_user_ids.add(int(row.user_id))

    payment_failed_last_30_days = sum(
        1
        for row in all_events
        if (row.status or "").lower() == "failed"
        and row.event_at is not None
        and row.event_at >= window_start
    )

    labels = _month_labels(resolved_now, months)
    revenue_by_month = {label: 0 for label in labels}
    for row in all_events:
        if (row.status or "").lower() != "succeeded":
            continue
        if row.amount_cents is None or int(row.amount_cents) <= 0:
            continue
        if row.event_at is None:
            continue
        label = row.event_at.strftime("%Y-%m")
        if label in revenue_by_month:
            revenue_by_month[label] += int(row.amount_cents)

    monthly_revenue = [
        SubscriptionDashboardRevenuePoint(month=label, revenue_cents=revenue_by_month[label])
        for label in labels
    ]

    current_month_label = resolved_now.strftime("%Y-%m")
    overview = SubscriptionDashboardOverview(
        users_free=users_by_plan[PLAN_FREE],
        users_pro=users_by_plan[PLAN_PRO],
        users_founder=users_by_plan[PLAN_FOUNDER],
        active_subscriptions=active_subscriptions,
        trialing_subscriptions=trialing_subscriptions,
        expiring_within_7_days=expiring_within_7_days,
        expiring_within_30_days=expiring_within_30_days,
        canceled_subscriptions=canceled_subscriptions,
        canceled_last_30_days=canceled_last_30_days,
        payment_failed_last_30_days=payment_failed_last_30_days,
        monthly_revenue_cents=revenue_by_month.get(current_month_label, 0),
        free_to_pro_users=free_to_pro_users,
        free_user_base=free_user_base,
        free_to_pro_conversion_pct=_pct(free_to_pro_users, free_user_base),
        churned_last_30_days=len(churned_user_ids),
        active_base_last_30_days=len(active_base_user_ids),
        churn_pct_last_30_days=_pct(len(churned_user_ids), len(active_base_user_ids)),
    )

    return SubscriptionDashboardSummaryResponse(
        generated_at=resolved_now,
        overview=overview,
        monthly_revenue=monthly_revenue,
    )


def list_subscription_dashboard_users(
    db: Session,
    *,
    q: str | None = None,
    plan_code: str | None = None,
    subscription_status: str | None = None,
    payment_failed: bool | None = None,
    trialing_only: bool = False,
    expiring_within_days: int | None = None,
    cancel_at_period_end: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    now: datetime | None = None,
) -> SubscriptionDashboardUserListResponse:
    """Return user-level subscription rows with search and lifecycle filters."""

    seed_default_plans(db, commit=False)
    resolved_now = now or _utc_now_naive()
    cleaned_plan = (_normalize_text(plan_code, 32) or "").lower()
    cleaned_status = (_normalize_text(subscription_status, 32) or "").lower()

    rows: list[SubscriptionDashboardUserRow] = []
    for user in _list_users_with_context(db):
        if not _matches_search(user, q):
            continue

        subscription = _resolve_current_or_latest_subscription(user, at=resolved_now)
        plan = subscription.plan if subscription is not None else None
        plan_code_value = (plan.code if plan is not None else None) or None
        status_value = (subscription.status if subscription is not None else None) or None

        latest_payment = _latest_payment_for_subscription(
            user,
            subscription.id if subscription is not None else None,
        )
        has_failed_payment = _has_failed_payment(
            user,
            subscription.id if subscription is not None else None,
        )

        if cleaned_plan and (plan_code_value or "").lower() != cleaned_plan:
            continue
        if cleaned_status and (status_value or "").lower() != cleaned_status:
            continue
        if trialing_only and (status_value or "").lower() != SUB_STATUS_TRIALING:
            continue
        if payment_failed is not None and has_failed_payment != payment_failed:
            continue
        if (
            cancel_at_period_end is not None
            and subscription is not None
            and bool(subscription.cancel_at_period_end) != cancel_at_period_end
        ):
            continue
        if cancel_at_period_end is not None and subscription is None and cancel_at_period_end:
            continue

        if expiring_within_days is not None:
            if subscription is None or subscription.expires_at is None:
                continue
            if subscription.expires_at < resolved_now:
                continue
            if subscription.expires_at > resolved_now + timedelta(days=max(0, expiring_within_days)):
                continue

        rows.append(
            SubscriptionDashboardUserRow(
                user_id=user.id,
                telegram_user_id=user.telegram_user_id,
                external_ref=user.external_ref,
                username=user.username,
                plan_code=plan_code_value,
                plan_name=plan.name if plan is not None else None,
                subscription_id=subscription.id if subscription is not None else None,
                subscription_status=status_value,
                started_at=subscription.started_at if subscription is not None else None,
                trial_ends_at=subscription.trial_ends_at if subscription is not None else None,
                expires_at=subscription.expires_at if subscription is not None else None,
                cancel_at_period_end=bool(subscription.cancel_at_period_end)
                if subscription is not None
                else False,
                canceled_at=subscription.canceled_at if subscription is not None else None,
                auto_renew=bool(subscription.auto_renew) if subscription is not None else False,
                payment_failed=has_failed_payment,
                last_payment_status=latest_payment.status if latest_payment is not None else None,
                last_payment_event_at=latest_payment.event_at if latest_payment is not None else None,
            )
        )

    rows.sort(key=lambda row: _latest_key(row.started_at, row.user_id), reverse=True)

    total = len(rows)
    bounded_limit = max(1, min(int(limit), 50000))
    bounded_offset = max(0, int(offset))
    page = rows[bounded_offset : bounded_offset + bounded_limit]

    return SubscriptionDashboardUserListResponse(
        total=total,
        limit=bounded_limit,
        offset=bounded_offset,
        items=page,
    )


def list_subscription_dashboard_events(
    db: Session,
    *,
    q: str | None = None,
    source: str | None = None,
    event_type: str | None = None,
    user_id: int | None = None,
    subscription_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SubscriptionDashboardEventListResponse:
    """Return combined payment + admin-action timeline for subscription operations."""

    cleaned_query = (_normalize_text(q, 255) or "").lower()
    cleaned_source = (_normalize_text(source, 32) or "").lower()
    cleaned_event_type = (_normalize_text(event_type, 64) or "").lower()

    payment_rows = (
        db.execute(
            select(PaymentEvent).options(
                joinedload(PaymentEvent.subscription).joinedload(Subscription.plan),
                joinedload(PaymentEvent.user),
            )
        )
        .unique()
        .scalars()
        .all()
    )
    admin_rows = (
        db.execute(
            select(AdminAuditLog).options(joinedload(AdminAuditLog.admin_user))
        )
        .scalars()
        .all()
    )

    items: list[SubscriptionDashboardEventRow] = []

    for row in payment_rows:
        item = SubscriptionDashboardEventRow(
            source="payment",
            event_id=f"payment:{row.id}",
            occurred_at=row.event_at,
            event_type=row.event_type,
            status=row.status,
            user_id=row.user_id,
            subscription_id=row.subscription_id,
            plan_code=row.subscription.plan.code
            if row.subscription is not None and row.subscription.plan is not None
            else None,
            amount_cents=row.amount_cents,
            currency=row.currency,
            admin_username=None,
            description=(
                f"provider={row.provider}"
                + (f" event={row.provider_event_id}" if row.provider_event_id else "")
            ),
            context_json=row.raw_payload_json,
        )
        items.append(item)

    for row in admin_rows:
        context = _parse_context(row.context_json)
        item = SubscriptionDashboardEventRow(
            source="admin_action",
            event_id=f"admin:{row.id}",
            occurred_at=row.created_at,
            event_type=row.action,
            status=_normalize_text(str(context.get("status")) if "status" in context else None, 32),
            user_id=_safe_int(context.get("user_id")),
            subscription_id=_safe_int(context.get("subscription_id")),
            plan_code=_normalize_text(
                str(context.get("plan_code")) if "plan_code" in context else None,
                32,
            ),
            amount_cents=None,
            currency=None,
            admin_username=row.admin_user.username if row.admin_user is not None else None,
            description=row.description,
            context_json=row.context_json,
        )
        items.append(item)

    filtered: list[SubscriptionDashboardEventRow] = []
    for row in items:
        if cleaned_source and row.source != cleaned_source:
            continue
        if cleaned_event_type and cleaned_event_type != (row.event_type or "").lower():
            continue
        if user_id is not None and row.user_id != user_id:
            continue
        if subscription_id is not None and row.subscription_id != subscription_id:
            continue
        if cleaned_query:
            haystack = " ".join(
                [
                    row.event_type or "",
                    row.description or "",
                    row.admin_username or "",
                    str(row.user_id) if row.user_id is not None else "",
                    row.plan_code or "",
                ]
            ).lower()
            if cleaned_query not in haystack:
                continue
        filtered.append(row)

    filtered.sort(key=lambda row: _latest_key(row.occurred_at, _safe_int(row.event_id.split(":")[-1])), reverse=True)

    total = len(filtered)
    bounded_limit = max(1, min(int(limit), 500))
    bounded_offset = max(0, int(offset))

    return SubscriptionDashboardEventListResponse(
        total=total,
        limit=bounded_limit,
        offset=bounded_offset,
        items=filtered[bounded_offset : bounded_offset + bounded_limit],
    )


def export_subscription_dashboard_users_csv(
    db: Session,
    *,
    q: str | None = None,
    plan_code: str | None = None,
    subscription_status: str | None = None,
    payment_failed: bool | None = None,
    trialing_only: bool = False,
    expiring_within_days: int | None = None,
    cancel_at_period_end: bool | None = None,
    now: datetime | None = None,
) -> tuple[str, int]:
    """Export filtered user rows as CSV text and return row count."""

    payload = list_subscription_dashboard_users(
        db,
        q=q,
        plan_code=plan_code,
        subscription_status=subscription_status,
        payment_failed=payment_failed,
        trialing_only=trialing_only,
        expiring_within_days=expiring_within_days,
        cancel_at_period_end=cancel_at_period_end,
        limit=50000,
        offset=0,
        now=now,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "user_id",
            "telegram_user_id",
            "username",
            "external_ref",
            "plan_code",
            "plan_name",
            "subscription_id",
            "subscription_status",
            "started_at",
            "trial_ends_at",
            "expires_at",
            "cancel_at_period_end",
            "canceled_at",
            "auto_renew",
            "payment_failed",
            "last_payment_status",
            "last_payment_event_at",
        ]
    )

    for row in payload.items:
        writer.writerow(
            [
                row.user_id,
                row.telegram_user_id or "",
                row.username or "",
                row.external_ref or "",
                row.plan_code or "",
                row.plan_name or "",
                row.subscription_id or "",
                row.subscription_status or "",
                row.started_at.isoformat() if row.started_at is not None else "",
                row.trial_ends_at.isoformat() if row.trial_ends_at is not None else "",
                row.expires_at.isoformat() if row.expires_at is not None else "",
                row.cancel_at_period_end,
                row.canceled_at.isoformat() if row.canceled_at is not None else "",
                row.auto_renew,
                row.payment_failed,
                row.last_payment_status or "",
                row.last_payment_event_at.isoformat() if row.last_payment_event_at is not None else "",
            ]
        )

    return buffer.getvalue(), payload.total


def log_admin_action(
    db: Session,
    *,
    admin: AdminUser,
    action: str,
    target_type: str,
    target_id: str | None,
    description: str | None,
    context: dict[str, Any] | None = None,
    commit: bool = False,
) -> AdminAuditLog:
    """Write a normalized admin audit row for manual dashboard operations."""

    row = AdminAuditLog(
        admin_user_id=admin.id,
        action=_normalize_text(action, 64) or "admin_action",
        target_type=_normalize_text(target_type, 64) or "unknown",
        target_id=_normalize_text(target_id, 128),
        description=_normalize_text(description, 255),
        context_json=_serialize_context(context),
        created_at=_utc_now_naive(),
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def suspend_subscription_as_admin(
    db: Session,
    *,
    admin: AdminUser,
    subscription_id: int,
    reason: str | None,
) -> SubscriptionRead:
    """Suspend a subscription and persist an admin audit trail row."""

    updated = suspend_subscription(
        db,
        subscription_id,
        reason=reason,
        now=_utc_now_naive(),
        commit=False,
    )
    log_admin_action(
        db,
        admin=admin,
        action="subscription_suspend",
        target_type="subscription",
        target_id=str(subscription_id),
        description="Manual suspension from admin dashboard",
        context={
            "subscription_id": subscription_id,
            "status": updated.status,
            "reason": reason,
            "user_id": updated.user_id,
        },
        commit=False,
    )
    db.commit()
    return updated


def resume_subscription_as_admin(
    db: Session,
    *,
    admin: AdminUser,
    subscription_id: int,
) -> SubscriptionRead:
    """Resume a subscription and persist an admin audit trail row."""

    updated = resume_subscription(
        db,
        subscription_id,
        now=_utc_now_naive(),
        commit=False,
    )
    log_admin_action(
        db,
        admin=admin,
        action="subscription_resume",
        target_type="subscription",
        target_id=str(subscription_id),
        description="Manual resume from admin dashboard",
        context={
            "subscription_id": subscription_id,
            "status": updated.status,
            "user_id": updated.user_id,
        },
        commit=False,
    )
    db.commit()
    return updated


def cancel_subscription_as_admin(
    db: Session,
    *,
    admin: AdminUser,
    subscription_id: int,
    immediate: bool,
    reason: str | None,
) -> SubscriptionRead:
    """Cancel a subscription and persist an admin audit trail row."""

    updated = cancel_subscription(
        db,
        subscription_id,
        immediate=immediate,
        reason=reason,
        now=_utc_now_naive(),
        commit=False,
    )
    log_admin_action(
        db,
        admin=admin,
        action="subscription_cancel",
        target_type="subscription",
        target_id=str(subscription_id),
        description="Manual cancellation from admin dashboard",
        context={
            "subscription_id": subscription_id,
            "status": updated.status,
            "immediate": bool(immediate),
            "reason": reason,
            "user_id": updated.user_id,
        },
        commit=False,
    )
    db.commit()
    return updated


def ensure_subscription_exists(subscription_id: int) -> None:
    if int(subscription_id) <= 0:
        raise SubscriptionError("subscription_id non valido.", status_code=400)


