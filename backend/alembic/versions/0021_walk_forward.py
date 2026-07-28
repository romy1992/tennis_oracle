"""walk-forward validation runs and folds

Revision ID: 0021_walk_forward
Revises: 0020_weekly_beta_report
Create Date: 2026-07-27

Adds walk_forward_run / walk_forward_fold for temporal walk-forward
validation results (separate from holdout baseline metrics and live KPIs).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0021_walk_forward"
down_revision: Union[str, None] = "0020_weekly_beta_report"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "walk_forward_run" not in tables:
        op.create_table(
            "walk_forward_run",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("mode", sa.String(length=16), nullable=False),
            sa.Column("initial_train_days", sa.Integer(), nullable=False),
            sa.Column("test_days", sa.Integer(), nullable=False),
            sa.Column("step_days", sa.Integer(), nullable=False),
            sa.Column("min_train_rows", sa.Integer(), nullable=False),
            sa.Column("min_test_rows", sa.Integer(), nullable=False),
            sa.Column("embargo_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("edge_threshold", sa.Float(), nullable=False),
            sa.Column("random_state", sa.Integer(), nullable=False, server_default="42"),
            sa.Column("versions_requested", sa.String(length=64), nullable=False),
            sa.Column("origin", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("report_path", sa.String(length=512), nullable=True),
            sa.Column("summary_json", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.String(length=64), nullable=False, server_default="api"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_walk_forward_run_status", "walk_forward_run", ["status"])

    if "walk_forward_fold" not in tables:
        op.create_table(
            "walk_forward_fold",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("fold_index", sa.Integer(), nullable=False),
            sa.Column("model_version", sa.String(length=8), nullable=False),
            sa.Column("model_name", sa.String(length=64), nullable=False),
            sa.Column("dataset_path", sa.String(length=512), nullable=False),
            sa.Column("status", sa.String(length=48), nullable=False),
            sa.Column("train_start", sa.Date(), nullable=False),
            sa.Column("train_end", sa.Date(), nullable=False),
            sa.Column("test_start", sa.Date(), nullable=False),
            sa.Column("test_end", sa.Date(), nullable=False),
            sa.Column("train_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("test_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("feature_set_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("metrics_json", sa.Text(), nullable=True),
            sa.Column("market_benchmark_json", sa.Text(), nullable=True),
            sa.Column("coverage_json", sa.Text(), nullable=True),
            sa.Column("leakage_flags_json", sa.Text(), nullable=True),
            sa.Column("skip_reason", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["run_id"], ["walk_forward_run.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "run_id",
                "model_version",
                "model_name",
                "fold_index",
                name="uq_walk_forward_fold_identity",
            ),
        )
        op.create_index("ix_walk_forward_fold_run_id", "walk_forward_fold", ["run_id"])
        op.create_index("ix_walk_forward_fold_model_version", "walk_forward_fold", ["model_version"])
        op.create_index("ix_walk_forward_fold_model_name", "walk_forward_fold", ["model_name"])
        op.create_index("ix_walk_forward_fold_status", "walk_forward_fold", ["status"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "walk_forward_fold" in tables:
        op.drop_index("ix_walk_forward_fold_status", table_name="walk_forward_fold")
        op.drop_index("ix_walk_forward_fold_model_name", table_name="walk_forward_fold")
        op.drop_index("ix_walk_forward_fold_model_version", table_name="walk_forward_fold")
        op.drop_index("ix_walk_forward_fold_run_id", table_name="walk_forward_fold")
        op.drop_table("walk_forward_fold")
    if "walk_forward_run" in tables:
        op.drop_index("ix_walk_forward_run_status", table_name="walk_forward_run")
        op.drop_table("walk_forward_run")
