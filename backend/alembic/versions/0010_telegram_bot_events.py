"""telegram bot analytics events

Revision ID: 0010_telegram_bot_events
Revises: 0009_pick_min_edge_fields
Create Date: 2026-07-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0010_telegram_bot_events"
down_revision: Union[str, None] = "0009_pick_min_edge_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "telegram_bot_event" in tables:
        return

    op.create_table(
        "telegram_bot_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("raw_text", sa.String(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_telegram_bot_event_created_at"),
        "telegram_bot_event",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_bot_event_telegram_user_id"),
        "telegram_bot_event",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_bot_event_chat_id"),
        "telegram_bot_event",
        ["chat_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_telegram_bot_event_action"),
        "telegram_bot_event",
        ["action"],
        unique=False,
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "telegram_bot_event" not in tables:
        return

    op.drop_index(op.f("ix_telegram_bot_event_action"), table_name="telegram_bot_event")
    op.drop_index(op.f("ix_telegram_bot_event_chat_id"), table_name="telegram_bot_event")
    op.drop_index(op.f("ix_telegram_bot_event_telegram_user_id"), table_name="telegram_bot_event")
    op.drop_index(op.f("ix_telegram_bot_event_created_at"), table_name="telegram_bot_event")
    op.drop_table("telegram_bot_event")
