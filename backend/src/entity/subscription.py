"""Subscription domain entities (plans, lifecycle, entitlements, audit events)."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.src.entity.base import Base


class User(Base):
    """End-user identity used by the subscription domain."""

    __tablename__ = "app_user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(BigInteger, nullable=True, unique=True, index=True)
    external_ref = Column(String(191), nullable=True, unique=True, index=True)
    username = Column(String(255), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    subscriptions = relationship(
        "Subscription",
        back_populates="user",
        order_by="Subscription.created_at",
    )
    payment_events = relationship(
        "PaymentEvent",
        back_populates="user",
        order_by="PaymentEvent.event_at",
    )
    payment_customers = relationship(
        "PaymentCustomer",
        back_populates="user",
        order_by="PaymentCustomer.created_at",
        cascade="all, delete-orphan",
    )
    checkout_sessions = relationship(
        "PaymentCheckoutSession",
        back_populates="user",
        order_by="PaymentCheckoutSession.created_at",
        cascade="all, delete-orphan",
    )
    access_logs = relationship(
        "AccessLog",
        back_populates="user",
        order_by="AccessLog.requested_at",
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class PaymentCustomer(Base):
    """Stable mapping between local user and external payment provider customer."""

    __tablename__ = "payment_customer"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_payment_customer_user_provider"),
        UniqueConstraint(
            "provider",
            "provider_customer_id",
            name="uq_payment_customer_provider_customer",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app_user.id"), nullable=False, index=True)
    provider = Column(String(64), nullable=False, default="stripe", index=True)
    provider_customer_id = Column(String(191), nullable=False)
    status = Column(String(32), nullable=False, default="active", index=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    user = relationship("User", back_populates="payment_customers")
    checkout_sessions = relationship(
        "PaymentCheckoutSession",
        back_populates="customer",
        order_by="PaymentCheckoutSession.created_at",
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class PaymentCheckoutSession(Base):
    """Checkout creation ledger used for idempotency and webhook reconciliation."""

    __tablename__ = "payment_checkout_session"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "idempotency_key",
            name="uq_payment_checkout_provider_idempotency",
        ),
        UniqueConstraint(
            "provider",
            "provider_session_id",
            name="uq_payment_checkout_provider_session",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app_user.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("payment_customer.id"), nullable=True, index=True)
    provider = Column(String(64), nullable=False, default="stripe", index=True)
    idempotency_key = Column(String(128), nullable=False)
    provider_session_id = Column(String(191), nullable=True)
    provider_subscription_id = Column(String(191), nullable=True)
    plan_code = Column(String(32), nullable=False, index=True)
    billing_cycle = Column(String(16), nullable=False, default="monthly", index=True)
    status = Column(String(32), nullable=False, default="created", index=True)
    checkout_url = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)
    raw_payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    user = relationship("User", back_populates="checkout_sessions")
    customer = relationship("PaymentCustomer", back_populates="checkout_sessions")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class Plan(Base):
    """Commercial plan (Free/Pro/Founder) with dynamic entitlement matrix."""

    __tablename__ = "plan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), nullable=False, unique=True, index=True)
    name = Column(String(64), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    billing_period_days = Column(Integer, nullable=False, default=30)
    price_cents = Column(Integer, nullable=True)
    currency = Column(String(8), nullable=True)
    trial_days = Column(Integer, nullable=False, default=0)
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    entitlements = relationship(
        "Entitlement",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="Entitlement.code",
    )
    subscriptions = relationship(
        "Subscription",
        back_populates="plan",
        order_by="Subscription.created_at",
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class Entitlement(Base):
    """Feature-level permission assigned to a plan (data-driven, no handler hardcode)."""

    __tablename__ = "entitlement"
    __table_args__ = (
        UniqueConstraint("plan_id", "code", name="uq_entitlement_plan_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("plan.id"), nullable=False, index=True)
    code = Column(String(128), nullable=False, index=True)
    is_enabled = Column(Boolean, nullable=False, default=True)
    value = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    plan = relationship("Plan", back_populates="entitlements")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class Subscription(Base):
    """Plan assignment and lifecycle state for one user."""

    __tablename__ = "subscription"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app_user.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("plan.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="active", index=True)
    started_at = Column(DateTime, nullable=False)
    current_period_start_at = Column(DateTime, nullable=True)
    current_period_end_at = Column(DateTime, nullable=True)
    trial_started_at = Column(DateTime, nullable=True)
    trial_ends_at = Column(DateTime, nullable=True)
    renewed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    auto_renew = Column(Boolean, nullable=False, default=True)
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    canceled_at = Column(DateTime, nullable=True)
    cancellation_reason = Column(String(255), nullable=True)
    suspended_at = Column(DateTime, nullable=True)
    suspension_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    user = relationship("User", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")
    payment_events = relationship(
        "PaymentEvent",
        back_populates="subscription",
        order_by="PaymentEvent.event_at",
        cascade="all, delete-orphan",
    )
    access_logs = relationship(
        "AccessLog",
        back_populates="subscription",
        order_by="AccessLog.requested_at",
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class PaymentEvent(Base):
    """Billing events associated with subscription lifecycle and renewals."""

    __tablename__ = "payment_event"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_payment_event_provider_event",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, ForeignKey("subscription.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("app_user.id"), nullable=False, index=True)
    provider = Column(String(64), nullable=False, default="manual")
    provider_event_id = Column(String(191), nullable=True)
    event_type = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    amount_cents = Column(Integer, nullable=True)
    currency = Column(String(8), nullable=True)
    event_at = Column(DateTime, nullable=False, index=True)
    raw_payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)

    subscription = relationship("Subscription", back_populates="payment_events")
    user = relationship("User", back_populates="payment_events")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class AccessLog(Base):
    """Authorization audit trail for entitlement checks (API, bot, dashboard)."""

    __tablename__ = "access_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app_user.id"), nullable=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscription.id"), nullable=True, index=True)
    plan_code = Column(String(32), nullable=True, index=True)
    source = Column(String(64), nullable=False, index=True)
    resource = Column(String(128), nullable=False)
    entitlement_code = Column(String(128), nullable=True, index=True)
    allowed = Column(Boolean, nullable=False, index=True)
    reason = Column(String(64), nullable=True)
    requested_at = Column(DateTime, nullable=False, index=True)
    context_json = Column(Text, nullable=True)

    user = relationship("User", back_populates="access_logs")
    subscription = relationship("Subscription", back_populates="access_logs")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

