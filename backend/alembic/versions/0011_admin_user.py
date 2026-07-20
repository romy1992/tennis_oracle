"""admin_user table for dashboard authentication

Revision ID: 0011_admin_user
Revises: 0010_telegram_bot_events
Create Date: 2026-07-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0011_admin_user"
down_revision: Union[str, None] = "0010_telegram_bot_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "admin_user" in tables:
        return

    op.create_table(
        "admin_user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_admin_user_username"), "admin_user", ["username"], unique=True)


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "admin_user" not in tables:
        return

    op.drop_index(op.f("ix_admin_user_username"), table_name="admin_user")
    op.drop_table("admin_user")
