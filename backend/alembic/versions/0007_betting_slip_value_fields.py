"""betting slip value analysis fields

Revision ID: 0007_betting_slip_value_fields
Revises: 0006_betting_slip_day
Create Date: 2026-07-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0007_betting_slip_value_fields"
down_revision: Union[str, None] = "0006_betting_slip_day"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VALUE_COLUMNS = {
    "void_odds": sa.Float(),
    "edge_absolute": sa.Float(),
    "edge_percent": sa.Float(),
    "expected_roi": sa.Float(),
    "value_decision": sa.String(),
    "value_label": sa.String(),
}


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "betting_slip_pick" not in tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("betting_slip_pick")}
    for column_name, column_type in VALUE_COLUMNS.items():
        if column_name not in existing_columns:
            op.add_column(
                "betting_slip_pick",
                sa.Column(column_name, column_type, nullable=True),
            )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "betting_slip_pick" not in tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("betting_slip_pick")}
    for column_name in reversed(tuple(VALUE_COLUMNS)):
        if column_name in existing_columns:
            op.drop_column("betting_slip_pick", column_name)
