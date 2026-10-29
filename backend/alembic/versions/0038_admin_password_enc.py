"""admin_user.password_enc (copia cifrata per l'occhio nelle Impostazioni)

Revision ID: 0038_admin_password_enc
Revises: 0037_scheduled_job_settings
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "0038_admin_password_enc"
down_revision: str | None = "0037_scheduled_job_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("admin_user")}
    if "password_enc" not in columns:
        op.add_column("admin_user", sa.Column("password_enc", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_user", "password_enc")
