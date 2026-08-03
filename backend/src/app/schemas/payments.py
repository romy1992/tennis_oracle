"""Pydantic schemas for payment checkout and webhook flows."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


PaymentProviderCode = Literal["stripe"]
BillingCycle = Literal["monthly", "yearly"]


class PaymentCheckoutCreate(BaseModel):
    telegram_user_id: int = Field(..., gt=0)
    username: str | None = Field(default=None, max_length=255)
    plan_code: str = Field(default="pro", min_length=1, max_length=32)
    billing_cycle: BillingCycle = "monthly"
    success_url: HttpUrl | None = None
    cancel_url: HttpUrl | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class PaymentCheckoutRead(BaseModel):
    provider: PaymentProviderCode | str
    mode: str
    idempotency_key: str
    checkout_url: str
    session_id: str
    customer_id: str
    plan_code: str
    billing_cycle: BillingCycle | str
    expires_at: datetime | None = None
    reused: bool = False


class PaymentCustomerPortalRead(BaseModel):
    provider: PaymentProviderCode | str
    mode: str
    portal_url: str
    expires_at: datetime | None = None


class PaymentCustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    provider: str
    provider_customer_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class PaymentWebhookAck(BaseModel):
    ok: bool = True
    processed: bool
    event_id: str | None = None
    event_type: str | None = None
    duplicate: bool = False
    message: str | None = None


