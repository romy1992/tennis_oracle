"""telegram notification prefs and delivery ledger

Revision ID: 0018_telegram_notifications
Revises: 0017_telegram_user
Create Date: 2026-07-27

Adds chat_id + notification preferences on telegram_user, and
telegram_notification_delivery for durable outbound delivery / dedupe / errors.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0018_telegram_notifications"
down_revision: Union[str, None] = "0017_telegram_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in set(inspector.get_table_names()):
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "telegram_user" in tables:
        if not _has_column(inspector, "telegram_user", "chat_id"):
            op.add_column(
                "telegram_user",
                sa.Column("chat_id", sa.BigInteger(), nullable=True),
            )
            op.create_index("ix_telegram_user_chat_id", "telegram_user", ["chat_id"])
        if not _has_column(inspector, "telegram_user", "notifications_enabled"):
            op.add_column(
                "telegram_user",
                sa.Column(
                    "notifications_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("true"),
                ),
            )
        if not _has_column(inspector, "telegram_user", "notify_predictions"):
            op.add_column(
                "telegram_user",
                sa.Column(
                    "notify_predictions",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("true"),
                ),
            )
        if not _has_column(inspector, "telegram_user", "notify_results"):
            op.add_column(
                "telegram_user",
                sa.Column(
                    "notify_results",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("true"),
                ),
            )
        if not _has_column(inspector, "telegram_user", "notify_empty_day"):
            op.add_column(
                "telegram_user",
                sa.Column(
                    "notify_empty_day",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("false"),
                ),
            )

    if "telegram_notification_delivery" not in tables:
        op.create_table(
            "telegram_notification_delivery",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dedupe_key", sa.String(length=191), nullable=False),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("content_date", sa.Date(), nullable=False),
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "dedupe_key",
                name="uq_telegram_notification_delivery_dedupe_key",
            ),
        )
        op.create_index(
            "ix_telegram_notification_delivery_kind",
            "telegram_notification_delivery",
            ["kind"],
        )
        op.create_index(
            "ix_telegram_notification_delivery_content_date",
            "telegram_notification_delivery",
            ["content_date"],
        )
        op.create_index(
            "ix_telegram_notification_delivery_telegram_user_id",
            "telegram_notification_delivery",
            ["telegram_user_id"],
        )
        op.create_index(
            "ix_telegram_notification_delivery_status",
            "telegram_notification_delivery",
            ["status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "telegram_notification_delivery" in tables:
        op.drop_index(
            "ix_telegram_notification_delivery_status",
            table_name="telegram_notification_delivery",
        )
        op.drop_index(
            "ix_telegram_notification_delivery_telegram_user_id",
            table_name="telegram_notification_delivery",
        )
        op.drop_index(
            "ix_telegram_notification_delivery_content_date",
            table_name="telegram_notification_delivery",
        )
        op.drop_index(
            "ix_telegram_notification_delivery_kind",
            table_name="telegram_notification_delivery",
        )
        op.drop_table("telegram_notification_delivery")

    if "telegram_user" in tables:
        if _has_column(inspector, "telegram_user", "notify_empty_day"):
            op.drop_column("telegram_user", "notify_empty_day")
        if _has_column(inspector, "telegram_user", "notify_results"):
            op.drop_column("telegram_user", "notify_results")
        if _has_column(inspector, "telegram_user", "notify_predictions"):
            op.drop_column("telegram_user", "notify_predictions")
        if _has_column(inspector, "telegram_user", "notifications_enabled"):
            op.drop_column("telegram_user", "notifications_enabled")
        if _has_column(inspector, "telegram_user", "chat_id"):
            op.drop_index("ix_telegram_user_chat_id", table_name="telegram_user")
            op.drop_column("telegram_user", "chat_id")
