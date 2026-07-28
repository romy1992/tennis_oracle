"""probability calibration runs and results

Revision ID: 0022_calibration
Revises: 0021_walk_forward
Create Date: 2026-07-28

Adds calibration_run / calibration_result for OOS walk-forward calibration
analysis (separate from production model artifacts and live KPIs).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0022_calibration"
down_revision: Union[str, None] = "0021_walk_forward"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "calibration_run" not in tables:
        op.create_table(
            "calibration_run",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("walk_forward_run_id", sa.Integer(), nullable=True),
            sa.Column("n_bins", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("min_bin_samples", sa.Integer(), nullable=False, server_default="30"),
            sa.Column(
                "min_calibrator_train_samples",
                sa.Integer(),
                nullable=False,
                server_default="100",
            ),
            sa.Column("wf_mode", sa.String(length=16), nullable=False),
            sa.Column("wf_initial_train_days", sa.Integer(), nullable=False),
            sa.Column("wf_test_days", sa.Integer(), nullable=False),
            sa.Column("wf_step_days", sa.Integer(), nullable=False),
            sa.Column("wf_min_train_rows", sa.Integer(), nullable=False),
            sa.Column("wf_min_test_rows", sa.Integer(), nullable=False),
            sa.Column("wf_embargo_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("wf_edge_threshold", sa.Float(), nullable=False),
            sa.Column("wf_random_state", sa.Integer(), nullable=False, server_default="42"),
            sa.Column(
                "methods_requested",
                sa.String(length=64),
                nullable=False,
                server_default="raw,platt,isotonic",
            ),
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
            sa.ForeignKeyConstraint(["walk_forward_run_id"], ["walk_forward_run.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_calibration_run_status", "calibration_run", ["status"])

    if "calibration_result" not in tables:
        op.create_table(
            "calibration_result",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("model_version", sa.String(length=8), nullable=False),
            sa.Column("model_name", sa.String(length=64), nullable=False),
            sa.Column("dataset_path", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("date_min", sa.String(length=16), nullable=True),
            sa.Column("date_max", sa.String(length=16), nullable=True),
            sa.Column("oos_samples_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metrics_json", sa.Text(), nullable=True),
            sa.Column("comparison_json", sa.Text(), nullable=True),
            sa.Column("fold_outcomes_json", sa.Text(), nullable=True),
            sa.Column("artifacts_json", sa.Text(), nullable=True),
            sa.Column("leakage_flags_json", sa.Text(), nullable=True),
            sa.Column("skip_reason", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["run_id"], ["calibration_run.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "run_id",
                "model_version",
                "model_name",
                name="uq_calibration_result_identity",
            ),
        )
        op.create_index("ix_calibration_result_run_id", "calibration_result", ["run_id"])
        op.create_index(
            "ix_calibration_result_model_version", "calibration_result", ["model_version"]
        )
        op.create_index("ix_calibration_result_model_name", "calibration_result", ["model_name"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "calibration_result" in tables:
        op.drop_index("ix_calibration_result_model_name", table_name="calibration_result")
        op.drop_index("ix_calibration_result_model_version", table_name="calibration_result")
        op.drop_index("ix_calibration_result_run_id", table_name="calibration_result")
        op.drop_table("calibration_result")
    if "calibration_run" in tables:
        op.drop_index("ix_calibration_run_status", table_name="calibration_run")
        op.drop_table("calibration_run")
