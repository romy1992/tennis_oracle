"""Schemas for the admin subscriptions dashboard (SUB-06)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.src.app.schemas.subscriptions import SubscriptionRead


class SubscriptionDashboardOverview(BaseModel):
    users_free: int = 0
    users_pro: int = 0
    users_founder: int = 0
    active_subscriptions: int = 0
    trialing_subscriptions: int = 0
    expiring_within_7_days: int = 0
    expiring_within_30_days: int = 0
    canceled_subscriptions: int = 0
    canceled_last_30_days: int = 0
    payment_failed_last_30_days: int = 0
    monthly_revenue_cents: int = 0
    free_to_pro_users: int = 0
    free_user_base: int = 0
    free_to_pro_conversion_pct: float | None = None
    churned_last_30_days: int = 0
    active_base_last_30_days: int = 0
    churn_pct_last_30_days: float | None = None


class SubscriptionDashboardRevenuePoint(BaseModel):
    month: str
    revenue_cents: int


class SubscriptionDashboardSummaryResponse(BaseModel):
    generated_at: datetime
    overview: SubscriptionDashboardOverview
    monthly_revenue: list[SubscriptionDashboardRevenuePoint] = Field(default_factory=list)


class SubscriptionDashboardUserRow(BaseModel):
    user_id: int
    telegram_user_id: int | None = None
    external_ref: str | None = None
    username: str | None = None
    plan_code: str | None = None
    plan_name: str | None = None
    subscription_id: int | None = None
    subscription_status: str | None = None
    started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    expires_at: datetime | None = None
    cancel_at_period_end: bool = False
    canceled_at: datetime | None = None
    auto_renew: bool = False
    payment_failed: bool = False
    last_payment_status: str | None = None
    last_payment_event_at: datetime | None = None


class SubscriptionDashboardUserListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SubscriptionDashboardUserRow] = Field(default_factory=list)


class SubscriptionDashboardEventRow(BaseModel):
    source: Literal["payment", "admin_action"]
    event_id: str
    occurred_at: datetime
    event_type: str
    status: str | None = None
    user_id: int | None = None
    subscription_id: int | None = None
    plan_code: str | None = None
    amount_cents: int | None = None
    currency: str | None = None
    admin_username: str | None = None
    description: str | None = None
    context_json: str | None = None


class SubscriptionDashboardEventListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SubscriptionDashboardEventRow] = Field(default_factory=list)


class SubscriptionDashboardSuspendRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class SubscriptionDashboardCancelRequest(BaseModel):
    immediate: bool = False
    reason: str | None = Field(default=None, max_length=255)


class SubscriptionDashboardManualActionResponse(BaseModel):
    message: str
    subscription: SubscriptionRead

