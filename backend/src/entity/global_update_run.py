"""Persisted global update runs and per model/version items."""

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


class GlobalUpdateRun(Base):
    """One global update execution (manual, cron, or CLI job)."""

    __tablename__ = "global_update_run"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_date = Column(Date, nullable=False, index=True)
    origin = Column(String, nullable=False)  # manual | cron | job
    status = Column(String, nullable=False, default="pending", index=True)
    current_phase = Column(String, nullable=True)
    progress_pct = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    force = Column(String, nullable=False, default="false")
    cancel_requested = Column(String, nullable=False, default="false")
    phases_json = Column(Text, nullable=True)
    worker_id = Column(String(64), nullable=True)
    resume_count = Column(Integer, nullable=False, default=0)
    sync_cloud = Column(String, nullable=False, default="false")
    versions_processed = Column(Integer, nullable=False, default=0)
    models_processed = Column(Integer, nullable=False, default=0)
    combinations_completed = Column(Integer, nullable=False, default=0)
    combinations_failed = Column(Integer, nullable=False, default=0)
    combinations_skipped = Column(Integer, nullable=False, default=0)
    fixtures_processed = Column(Integer, nullable=False, default=0)
    slips_generated = Column(Integer, nullable=False, default=0)
    report_json = Column(Text, nullable=True)
    errors_json = Column(Text, nullable=True)
    warnings_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)

    items = relationship(
        "GlobalUpdateRunItem",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="GlobalUpdateRunItem.id",
    )

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class GlobalUpdateRunItem(Base):
    """Result for one model_version + model_name within a global run."""

    __tablename__ = "global_update_run_item"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "model_version",
            "model_name",
            name="uq_global_update_run_item",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("global_update_run.id"), nullable=False, index=True)
    model_version = Column(String, nullable=False)
    model_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    predictions_generated = Column(Integer, nullable=False, default=0)
    slips_generated = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    warnings_json = Column(Text, nullable=True)

    run = relationship("GlobalUpdateRun", back_populates="items")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
