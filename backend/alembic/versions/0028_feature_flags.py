"""feature flags for runtime toggles

Revision ID: 0028_feature_flags
Revises: 0027_admin_audit_log
Create Date: 2026-08-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0028_feature_flags"
down_revision: Union[str, None] = "0027_admin_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "feature_flag" not in tables:
        op.create_table(
            "feature_flag",
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("updated_by", sa.String(length=150), nullable=True),
            sa.PrimaryKeyConstraint("key"),
        )
        op.create_index("ix_feature_flag_enabled", "feature_flag", ["enabled"])
        op.create_index("ix_feature_flag_updated_at", "feature_flag", ["updated_at"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "feature_flag" in tables:
        op.drop_table("feature_flag")

