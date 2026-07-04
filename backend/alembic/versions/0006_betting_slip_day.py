"""betting slip day calendar registry

Revision ID: 0006_betting_slip_day
Revises: 0005_betting_slips
Create Date: 2026-06-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "0006_betting_slip_day"
down_revision: Union[str, None] = "0005_betting_slips"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "betting_slip_day" not in tables:
        op.create_table(
            "betting_slip_day",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("slip_date", sa.Date(), nullable=False),
            sa.Column("model_version", sa.String(), nullable=False),
            sa.Column("model_name", sa.String(), nullable=False),
            sa.Column("candidate_pool_size", sa.Integer(), nullable=False),
            sa.Column("slip_count", sa.Integer(), nullable=False),
            sa.Column("fixture_count", sa.Integer(), nullable=False),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "slip_date",
                "model_version",
                "model_name",
                name="uq_betting_slip_day_date_model",
            ),
        )

    inspector = inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("betting_slip_day")}
    if "ix_betting_slip_day_slip_date" not in indexes:
        op.create_index(
            op.f("ix_betting_slip_day_slip_date"),
            "betting_slip_day",
            ["slip_date"],
            unique=False,
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "betting_slip_day" in tables:
        op.drop_table("betting_slip_day")
