"""add model name to match predictions

Revision ID: 0004_prediction_model_name
Revises: 0003_next_fixtures
Create Date: 2026-06-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "0004_prediction_model_name"
down_revision: Union[str, None] = "0003_next_fixtures"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("match_prediction")}
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("match_prediction")
    }

    if "model_name" not in columns:
        with op.batch_alter_table("match_prediction") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "model_name",
                    sa.String(),
                    nullable=False,
                    server_default="logistic_regression",
                )
            )

    if "uq_match_prediction_event_version" in unique_constraints:
        with op.batch_alter_table("match_prediction") as batch_op:
            batch_op.drop_constraint("uq_match_prediction_event_version", type_="unique")

    if "uq_match_prediction_event_version_model" not in unique_constraints:
        with op.batch_alter_table("match_prediction") as batch_op:
            batch_op.create_unique_constraint(
                "uq_match_prediction_event_version_model",
                ["event_key", "model_version", "model_name"],
            )

    with op.batch_alter_table("match_prediction") as batch_op:
        batch_op.alter_column("model_name", server_default=None)


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("match_prediction")}
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("match_prediction")
    }

    with op.batch_alter_table("match_prediction") as batch_op:
        if "uq_match_prediction_event_version_model" in unique_constraints:
            batch_op.drop_constraint("uq_match_prediction_event_version_model", type_="unique")
        if "uq_match_prediction_event_version" not in unique_constraints:
            batch_op.create_unique_constraint(
                "uq_match_prediction_event_version",
                ["event_key", "model_version"],
            )
        if "model_name" in columns:
            batch_op.drop_column("model_name")
