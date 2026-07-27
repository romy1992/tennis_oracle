"""telegram feedback inbox

Revision ID: 0019_telegram_feedback
Revises: 0018_telegram_notifications
Create Date: 2026-07-27

Adds telegram_feedback for in-bot /feedback submissions (category, rating,
message, user snapshot, status lifecycle).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0019_telegram_feedback"
down_revision: Union[str, None] = "0018_telegram_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "telegram_feedback" in tables:
        return

    op.create_table(
        "telegram_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_feedback_telegram_user_id",
        "telegram_feedback",
        ["telegram_user_id"],
    )
    op.create_index("ix_telegram_feedback_category", "telegram_feedback", ["category"])
    op.create_index("ix_telegram_feedback_status", "telegram_feedback", ["status"])
    op.create_index("ix_telegram_feedback_created_at", "telegram_feedback", ["created_at"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "telegram_feedback" not in tables:
        return
    op.drop_index("ix_telegram_feedback_created_at", table_name="telegram_feedback")
    op.drop_index("ix_telegram_feedback_status", table_name="telegram_feedback")
    op.drop_index("ix_telegram_feedback_category", table_name="telegram_feedback")
    op.drop_index("ix_telegram_feedback_telegram_user_id", table_name="telegram_feedback")
    op.drop_table("telegram_feedback")
