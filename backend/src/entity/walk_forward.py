"""Persisted walk-forward validation runs and per-fold outcomes."""

from sqlalchemy import (
    Column,
    Date,
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


class WalkForwardRun(Base):
    """One walk-forward execution across model versions (never updates public model)."""

    __tablename__ = "walk_forward_run"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    # expanding | rolling
    mode = Column(String(16), nullable=False)
    initial_train_days = Column(Integer, nullable=False)
    test_days = Column(Integer, nullable=False)
    step_days = Column(Integer, nullable=False)
    min_train_rows = Column(Integer, nullable=False)
    min_test_rows = Column(Integer, nullable=False)
    embargo_days = Column(Integer, nullable=False, default=0)
    edge_threshold = Column(Float, nullable=False)
    random_state = Column(Integer, nullable=False, default=42)
    # Comma-separated versions e.g. v1,v2,v3
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

    folds = relationship(
        "WalkForwardFold",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="WalkForwardFold.fold_index",
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class WalkForwardFold(Base):
    """Single fold outcome for one model version + estimator."""

    __tablename__ = "walk_forward_fold"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "model_version",
            "model_name",
            "fold_index",
            name="uq_walk_forward_fold_identity",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("walk_forward_run.id", ondelete="CASCADE"), nullable=False, index=True)
    fold_index = Column(Integer, nullable=False)
    model_version = Column(String(8), nullable=False, index=True)
    model_name = Column(String(64), nullable=False, index=True)
    dataset_path = Column(String(512), nullable=False)
    # completed | skipped_insufficient_data | skipped_single_class | error
    status = Column(String(48), nullable=False, index=True)
    train_start = Column(Date, nullable=False)
    train_end = Column(Date, nullable=False)
    test_start = Column(Date, nullable=False)
    test_end = Column(Date, nullable=False)
    train_rows = Column(Integer, nullable=False, default=0)
    test_rows = Column(Integer, nullable=False, default=0)
    feature_set_json = Column(Text, nullable=False, default="[]")
    metrics_json = Column(Text, nullable=True)
    market_benchmark_json = Column(Text, nullable=True)
    coverage_json = Column(Text, nullable=True)
    leakage_flags_json = Column(Text, nullable=True)
    skip_reason = Column(Text, nullable=True)

    run = relationship("WalkForwardRun", back_populates="folds")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
