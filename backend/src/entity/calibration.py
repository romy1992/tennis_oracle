"""Persisted probability calibration runs and per-model outcomes."""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.src.entity.base import Base


class CalibrationRun(Base):
    """One calibration analysis execution (OOS walk-forward; no public model change)."""

    __tablename__ = "calibration_run"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    walk_forward_run_id = Column(Integer, ForeignKey("walk_forward_run.id"), nullable=True)
    n_bins = Column(Integer, nullable=False, default=10)
    min_bin_samples = Column(Integer, nullable=False, default=30)
    min_calibrator_train_samples = Column(Integer, nullable=False, default=100)
    # Walk-forward window params (same semantics as walk_forward_run)
    wf_mode = Column(String(16), nullable=False)
    wf_initial_train_days = Column(Integer, nullable=False)
    wf_test_days = Column(Integer, nullable=False)
    wf_step_days = Column(Integer, nullable=False)
    wf_min_train_rows = Column(Integer, nullable=False)
    wf_min_test_rows = Column(Integer, nullable=False)
    wf_embargo_days = Column(Integer, nullable=False, default=0)
    wf_edge_threshold = Column(Float, nullable=False)
    wf_random_state = Column(Integer, nullable=False, default=42)
    methods_requested = Column(String(64), nullable=False, default="raw,platt,isotonic")
    versions_requested = Column(String(64), nullable=False)
    origin = Column(String(32), nullable=False, default="manual")
    current_phase = Column(String(256), nullable=True)
    progress_pct = Column(Float, nullable=True)
    progress_current = Column(Integer, nullable=True)
    progress_total = Column(Integer, nullable=True)
    cancel_requested = Column(String(8), nullable=False, default="false")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    report_path = Column(String(512), nullable=True)
    summary_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)
    created_by = Column(String(64), nullable=False, default="api")

    results = relationship(
        "CalibrationResult",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CalibrationResult.id",
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class CalibrationResult(Base):
    """Calibration outcome for one model version + estimator."""

    __tablename__ = "calibration_result"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "model_version",
            "model_name",
            name="uq_calibration_result_identity",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("calibration_run.id", ondelete="CASCADE"), nullable=False, index=True)
    model_version = Column(String(8), nullable=False, index=True)
    model_name = Column(String(64), nullable=False, index=True)
    dataset_path = Column(String(512), nullable=False, default="")
    date_min = Column(String(16), nullable=True)
    date_max = Column(String(16), nullable=True)
    oos_samples_total = Column(Integer, nullable=False, default=0)
    metrics_json = Column(Text, nullable=True)
    comparison_json = Column(Text, nullable=True)
    fold_outcomes_json = Column(Text, nullable=True)
    artifacts_json = Column(Text, nullable=True)
    leakage_flags_json = Column(Text, nullable=True)
    skip_reason = Column(Text, nullable=True)

    run = relationship("CalibrationRun", back_populates="results")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
