"""subscriptions domain base schema

Revision ID: 0025_subscriptions_domain
Revises: 0024_public_model_registry
Create Date: 2026-08-01

Introduces subscription domain tables:
- app_user
- plan
- entitlement
- subscription
- payment_event
- access_log
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0025_subscriptions_domain"
down_revision: Union[str, None] = "0024_public_model_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "app_user" not in tables:
        op.create_table(
            "app_user",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
            sa.Column("external_ref", sa.String(length=191), nullable=True),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "telegram_user_id",
                name="uq_app_user_telegram_user_id",
            ),
            sa.UniqueConstraint(
                "external_ref",
                name="uq_app_user_external_ref",
            ),
        )
        op.create_index("ix_app_user_telegram_user_id", "app_user", ["telegram_user_id"])
        op.create_index("ix_app_user_external_ref", "app_user", ["external_ref"])
        op.create_index("ix_app_user_username", "app_user", ["username"])
        op.create_index("ix_app_user_status", "app_user", ["status"])

    if "plan" not in tables:
        op.create_table(
            "plan",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("code", sa.String(length=32), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
            sa.Column(
                "billing_period_days",
                sa.Integer(),
                nullable=False,
                server_default="30",
            ),
            sa.Column("price_cents", sa.Integer(), nullable=True),
            sa.Column("currency", sa.String(length=8), nullable=True),
            sa.Column(
                "trial_days",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code", name="uq_plan_code"),
        )
        op.create_index("ix_plan_code", "plan", ["code"])
        op.create_index("ix_plan_status", "plan", ["status"])

    if "entitlement" not in tables:
        op.create_table(
            "entitlement",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("plan_id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=128), nullable=False),
            sa.Column(
                "is_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("value", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["plan_id"], ["plan.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("plan_id", "code", name="uq_entitlement_plan_code"),
        )
        op.create_index("ix_entitlement_plan_id", "entitlement", ["plan_id"])
        op.create_index("ix_entitlement_code", "entitlement", ["code"])

    if "subscription" not in tables:
        op.create_table(
            "subscription",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("plan_id", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("current_period_start_at", sa.DateTime(), nullable=True),
            sa.Column("current_period_end_at", sa.DateTime(), nullable=True),
            sa.Column("trial_started_at", sa.DateTime(), nullable=True),
            sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
            sa.Column("renewed_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column(
                "auto_renew",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "cancel_at_period_end",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("canceled_at", sa.DateTime(), nullable=True),
            sa.Column("cancellation_reason", sa.String(length=255), nullable=True),
            sa.Column("suspended_at", sa.DateTime(), nullable=True),
            sa.Column("suspension_reason", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["plan_id"], ["plan.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_subscription_user_id", "subscription", ["user_id"])
        op.create_index("ix_subscription_plan_id", "subscription", ["plan_id"])
        op.create_index("ix_subscription_status", "subscription", ["status"])
        op.create_index("ix_subscription_expires_at", "subscription", ["expires_at"])

    if "payment_event" not in tables:
        op.create_table(
            "payment_event",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("subscription_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column(
                "provider",
                sa.String(length=64),
                nullable=False,
                server_default="manual",
            ),
            sa.Column("provider_event_id", sa.String(length=191), nullable=True),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("amount_cents", sa.Integer(), nullable=True),
            sa.Column("currency", sa.String(length=8), nullable=True),
            sa.Column("event_at", sa.DateTime(), nullable=False),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["subscription_id"], ["subscription.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "provider_event_id",
                name="uq_payment_event_provider_event",
            ),
        )
        op.create_index("ix_payment_event_subscription_id", "payment_event", ["subscription_id"])
        op.create_index("ix_payment_event_user_id", "payment_event", ["user_id"])
        op.create_index("ix_payment_event_event_type", "payment_event", ["event_type"])
        op.create_index("ix_payment_event_status", "payment_event", ["status"])
        op.create_index("ix_payment_event_event_at", "payment_event", ["event_at"])

    if "access_log" not in tables:
        op.create_table(
            "access_log",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("subscription_id", sa.Integer(), nullable=True),
            sa.Column("plan_code", sa.String(length=32), nullable=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("resource", sa.String(length=128), nullable=False),
            sa.Column("entitlement_code", sa.String(length=128), nullable=True),
            sa.Column("allowed", sa.Boolean(), nullable=False),
            sa.Column("reason", sa.String(length=64), nullable=True),
            sa.Column("requested_at", sa.DateTime(), nullable=False),
            sa.Column("context_json", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["subscription_id"], ["subscription.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_access_log_user_id", "access_log", ["user_id"])
        op.create_index("ix_access_log_subscription_id", "access_log", ["subscription_id"])
        op.create_index("ix_access_log_plan_code", "access_log", ["plan_code"])
        op.create_index("ix_access_log_source", "access_log", ["source"])
        op.create_index("ix_access_log_entitlement_code", "access_log", ["entitlement_code"])
        op.create_index("ix_access_log_allowed", "access_log", ["allowed"])
        op.create_index("ix_access_log_requested_at", "access_log", ["requested_at"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    for table_name in (
        "access_log",
        "payment_event",
        "subscription",
        "entitlement",
        "plan",
        "app_user",
    ):
        if table_name in tables:
            op.drop_table(table_name)

