"""rate_limit_bucket table for multi-instance rate limiting

Revision ID: 0012_rate_limit_bucket
Revises: 0011_admin_user
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0012_rate_limit_bucket"
down_revision: Union[str, None] = "0011_admin_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "rate_limit_bucket" in tables:
        return

    op.create_table(
        "rate_limit_bucket",
        sa.Column("bucket_key", sa.String(length=255), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("bucket_key"),
    )
    op.create_index(
        "ix_rate_limit_bucket_window_start",
        "rate_limit_bucket",
        ["window_start"],
        unique=False,
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "rate_limit_bucket" not in tables:
        return

    op.drop_index("ix_rate_limit_bucket_window_start", table_name="rate_limit_bucket")
    op.drop_table("rate_limit_bucket")
