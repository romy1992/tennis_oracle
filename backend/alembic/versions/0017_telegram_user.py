"""telegram beta user registry

Revision ID: 0017_telegram_user
Revises: 0016_pipeline_reliability
Create Date: 2026-07-26

Adds telegram_user for beta whitelist: identity, access status, invite origin,
first/last access, and terms acceptance.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0017_telegram_user"
down_revision: Union[str, None] = "0016_pipeline_reliability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "telegram_user" in tables:
        return

    op.create_table(
        "telegram_user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="invited"),
        sa.Column("invite_origin", sa.String(length=255), nullable=True),
        sa.Column("first_access_at", sa.DateTime(), nullable=False),
        sa.Column("last_access_at", sa.DateTime(), nullable=False),
        sa.Column("terms_accepted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("terms_accepted_at", sa.DateTime(), nullable=True),
        sa.Column("terms_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id", name="uq_telegram_user_telegram_user_id"),
    )
    op.create_index("ix_telegram_user_telegram_user_id", "telegram_user", ["telegram_user_id"])
    op.create_index("ix_telegram_user_username", "telegram_user", ["username"])
    op.create_index("ix_telegram_user_status", "telegram_user", ["status"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "telegram_user" not in tables:
        return
    op.drop_index("ix_telegram_user_status", table_name="telegram_user")
    op.drop_index("ix_telegram_user_username", table_name="telegram_user")
    op.drop_index("ix_telegram_user_telegram_user_id", table_name="telegram_user")
    op.drop_table("telegram_user")
