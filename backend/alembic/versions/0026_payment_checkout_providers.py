"""payment provider checkout tables

Revision ID: 0026_payment_checkout_providers
Revises: 0025_subscriptions_domain
Create Date: 2026-08-01

Adds provider-agnostic payment mapping tables:
- payment_customer
- payment_checkout_session
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0026_payment_checkout_providers"
down_revision: Union[str, None] = "0025_subscriptions_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "payment_customer" not in tables:
        op.create_table(
            "payment_customer",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column(
                "provider",
                sa.String(length=64),
                nullable=False,
                server_default="stripe",
            ),
            sa.Column("provider_customer_id", sa.String(length=191), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id",
                "provider",
                name="uq_payment_customer_user_provider",
            ),
            sa.UniqueConstraint(
                "provider",
                "provider_customer_id",
                name="uq_payment_customer_provider_customer",
            ),
        )
        op.create_index("ix_payment_customer_user_id", "payment_customer", ["user_id"])
        op.create_index("ix_payment_customer_provider", "payment_customer", ["provider"])
        op.create_index("ix_payment_customer_status", "payment_customer", ["status"])

    if "payment_checkout_session" not in tables:
        op.create_table(
            "payment_checkout_session",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=True),
            sa.Column(
                "provider",
                sa.String(length=64),
                nullable=False,
                server_default="stripe",
            ),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("provider_session_id", sa.String(length=191), nullable=True),
            sa.Column("provider_subscription_id", sa.String(length=191), nullable=True),
            sa.Column("plan_code", sa.String(length=32), nullable=False),
            sa.Column(
                "billing_cycle",
                sa.String(length=16),
                nullable=False,
                server_default="monthly",
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="created",
            ),
            sa.Column("checkout_url", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("canceled_at", sa.DateTime(), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
            sa.ForeignKeyConstraint(["customer_id"], ["payment_customer.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider",
                "idempotency_key",
                name="uq_payment_checkout_provider_idempotency",
            ),
            sa.UniqueConstraint(
                "provider",
                "provider_session_id",
                name="uq_payment_checkout_provider_session",
            ),
        )
        op.create_index(
            "ix_payment_checkout_session_user_id",
            "payment_checkout_session",
            ["user_id"],
        )
        op.create_index(
            "ix_payment_checkout_session_customer_id",
            "payment_checkout_session",
            ["customer_id"],
        )
        op.create_index(
            "ix_payment_checkout_session_provider",
            "payment_checkout_session",
            ["provider"],
        )
        op.create_index(
            "ix_payment_checkout_session_plan_code",
            "payment_checkout_session",
            ["plan_code"],
        )
        op.create_index(
            "ix_payment_checkout_session_billing_cycle",
            "payment_checkout_session",
            ["billing_cycle"],
        )
        op.create_index(
            "ix_payment_checkout_session_status",
            "payment_checkout_session",
            ["status"],
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    for table_name in ("payment_checkout_session", "payment_customer"):
        if table_name in tables:
            op.drop_table(table_name)


