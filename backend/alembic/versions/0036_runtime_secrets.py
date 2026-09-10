"""add encrypted runtime secret storage

Revision ID: 0036_runtime_secrets
Revises: 0035_scheduled_report_jobs
Create Date: 2026-09-02

The table stores ciphertext and a non-reversible fingerprint only. The wrapping
key remains an environment-level deployment secret and is never persisted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "0036_runtime_secrets"
down_revision: str | None = "0035_scheduled_report_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "runtime_secret" in set(inspector.get_table_names()):
        return

    op.create_table(
        "runtime_secret",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("encryption_scheme", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=150), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        "ix_runtime_secret_updated_at",
        "runtime_secret",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "runtime_secret" in set(inspector.get_table_names()):
        op.drop_table("runtime_secret")
