"""Pydantic schemas for subscriptions and entitlements."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


UserStatus = Literal["active", "suspended", "disabled"]
PlanCode = Literal["free", "pro", "founder"]
PlanStatus = Literal["active", "disabled"]
SubscriptionStatus = Literal["trialing", "active", "canceled", "expired", "suspended"]
PaymentEventStatus = Literal["pending", "succeeded", "failed", "refunded"]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_user_id: int | None = None
    external_ref: str | None = None
    username: str | None = None
    status: UserStatus | str
    created_at: datetime
    updated_at: datetime


class EntitlementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    code: str
    is_enabled: bool
    value: str | None = None
    created_at: datetime
    updated_at: datetime


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: PlanCode | str
    name: str
    description: str | None = None
    status: PlanStatus | str
    billing_period_days: int
    price_cents: int | None = None
    currency: str | None = None
    trial_days: int
    is_default: bool
    created_at: datetime
    updated_at: datetime
    entitlements: list[EntitlementRead] = Field(default_factory=list)


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    plan_id: int
    status: SubscriptionStatus | str
    started_at: datetime
    current_period_start_at: datetime | None = None
    current_period_end_at: datetime | None = None
    trial_started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    renewed_at: datetime | None = None
    expires_at: datetime | None = None
    auto_renew: bool = True
    cancel_at_period_end: bool = False
    canceled_at: datetime | None = None
    cancellation_reason: str | None = None
    suspended_at: datetime | None = None
    suspension_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    plan: PlanRead | None = None


class PaymentEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subscription_id: int
    user_id: int
    provider: str
    provider_event_id: str | None = None
    event_type: str
    status: PaymentEventStatus | str
    amount_cents: int | None = None
    currency: str | None = None
    event_at: datetime
    raw_payload_json: str | None = None
    created_at: datetime


class AccessLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    subscription_id: int | None = None
    plan_code: str | None = None
    source: str
    resource: str
    entitlement_code: str | None = None
    allowed: bool
    reason: str | None = None
    requested_at: datetime
    context_json: str | None = None


class AccessDecision(BaseModel):
    allowed: bool
    reason: str | None = None
    entitlement_code: str
    user_id: int | None = None
    subscription_id: int | None = None
    plan_code: PlanCode | str | None = None
    subscription_status: SubscriptionStatus | str | None = None
    trial_ends_at: datetime | None = None
    expires_at: datetime | None = None
    checked_at: datetime


class UserUpsert(BaseModel):
    telegram_user_id: int | None = Field(default=None, gt=0)
    external_ref: str | None = Field(default=None, max_length=191)
    username: str | None = Field(default=None, max_length=255)


class SubscriptionCreate(BaseModel):
    user_id: int = Field(..., gt=0)
    plan_code: PlanCode | str
    started_at: datetime | None = None
    trial_days: int | None = Field(default=None, ge=0)
    period_days: int | None = Field(default=None, ge=1)


class SubscriptionRenew(BaseModel):
    period_days: int | None = Field(default=None, ge=1)
    provider: str = Field(default="manual", min_length=1, max_length=64)
    provider_event_id: str | None = Field(default=None, max_length=191)
    amount_cents: int | None = None
    currency: str | None = Field(default=None, max_length=8)


class SubscriptionCancel(BaseModel):
    immediate: bool = False
    reason: str | None = Field(default=None, max_length=255)


class SubscriptionSuspend(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class EntitlementCheckRequest(BaseModel):
    entitlement_code: str = Field(..., min_length=1, max_length=128)
    source: str = Field(default="api", min_length=1, max_length=64)
    resource: str = Field(default="unknown", min_length=1, max_length=128)

