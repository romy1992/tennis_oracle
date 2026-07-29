"""background job progress and cancel columns

Revision ID: 0023_background_job_progress
Revises: 0022_calibration
Create Date: 2026-07-29

Adds progress/cancel fields to walk_forward_run and calibration_run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0023_background_job_progress"
down_revision: Union[str, None] = "0022_calibration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROGRESS_COLUMNS = (
    ("current_phase", sa.String(), None),
    ("progress_pct", sa.Float(), None),
    ("progress_current", sa.Integer(), None),
    ("progress_total", sa.Integer(), None),
    ("cancel_requested", sa.String(length=8), "false"),
)


def _add_columns(table: str) -> None:
    inspector = inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table)}
    for name, col_type, server_default in _PROGRESS_COLUMNS:
        if name in existing:
            continue
        kwargs: dict = {"nullable": True}
        if server_default is not None:
            kwargs["server_default"] = server_default
            kwargs["nullable"] = False
        op.add_column(table, sa.Column(name, col_type, **kwargs))


def upgrade() -> None:
    _add_columns("walk_forward_run")
    _add_columns("calibration_run")


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    for table in ("walk_forward_run", "calibration_run"):
        if table not in inspector.get_table_names():
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, _, _ in reversed(_PROGRESS_COLUMNS):
            if name in existing:
                op.drop_column(table, name)
