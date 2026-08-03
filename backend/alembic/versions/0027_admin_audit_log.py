"""admin manual operations audit log

Revision ID: 0027_admin_audit_log
Revises: 0026_payment_checkout_providers
Create Date: 2026-08-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0027_admin_audit_log"
down_revision: Union[str, None] = "0026_payment_checkout_providers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "admin_audit_log" not in tables:
        op.create_table(
            "admin_audit_log",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("admin_user_id", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("target_type", sa.String(length=64), nullable=False),
            sa.Column("target_id", sa.String(length=128), nullable=True),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("context_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["admin_user_id"], ["admin_user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_admin_audit_log_admin_user_id", "admin_audit_log", ["admin_user_id"])
        op.create_index("ix_admin_audit_log_action", "admin_audit_log", ["action"])
        op.create_index("ix_admin_audit_log_target_type", "admin_audit_log", ["target_type"])
        op.create_index("ix_admin_audit_log_target_id", "admin_audit_log", ["target_id"])
        op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "admin_audit_log" in tables:
        op.drop_table("admin_audit_log")

