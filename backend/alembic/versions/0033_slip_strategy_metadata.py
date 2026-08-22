"""add strategy metadata to persisted betting slips

Revision ID: 0033_slip_strategy_metadata
Revises: 0032_daily_slip_lifecycle
Create Date: 2026-08-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0033_slip_strategy_metadata"
down_revision: Union[str, None] = "0032_daily_slip_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "betting_slip" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("betting_slip")}
    with op.batch_alter_table("betting_slip") as batch_op:
        if "strategy_family" not in columns:
            batch_op.add_column(
                sa.Column(
                    "strategy_family",
                    sa.String(),
                    nullable=False,
                    server_default="generic",
                )
            )
        if "strategy_version" not in columns:
            batch_op.add_column(
                sa.Column(
                    "strategy_version",
                    sa.String(),
                    nullable=False,
                    server_default="legacy_v1",
                )
            )
        if "is_experimental" not in columns:
            batch_op.add_column(
                sa.Column(
                    "is_experimental",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    # Existing rows are the immutable benchmark requested by the product: no
    # historical slip is regenerated or deleted.
    op.execute(
        sa.text(
            "UPDATE betting_slip "
            "SET strategy_family = 'generic', "
            "strategy_version = 'legacy_v1', "
            "is_experimental = false"
        )
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "betting_slip" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("betting_slip")}
    with op.batch_alter_table("betting_slip") as batch_op:
        if "is_experimental" in columns:
            batch_op.drop_column("is_experimental")
        if "strategy_version" in columns:
            batch_op.drop_column("strategy_version")
        if "strategy_family" in columns:
            batch_op.drop_column("strategy_family")
