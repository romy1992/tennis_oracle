"""Persisted scheduled report executions and their runtime provenance."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from backend.src.entity.base import Base


class ScheduledReportJob(Base):
    """One claimed daily or weekly schedule slot.

    ``schedule_key`` is globally unique inside the target database. This makes
    the scheduler safe when local, development, and production workers happen
    to point at the same database: only the first worker executes the slot.
    """

    __tablename__ = "scheduled_report_job"

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_key = Column(String(96), nullable=False, unique=True, index=True)
    job_name = Column(String(48), nullable=False, index=True)
    scheduled_for = Column(DateTime, nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)

    source_environment = Column(String(32), nullable=False)
    source_name = Column(String(128), nullable=False)
    source_url = Column(String(512), nullable=True)
    source_hostname = Column(String(255), nullable=False)
    source_path = Column(String(1024), nullable=False)

    global_update_run_id = Column(
        Integer,
        ForeignKey("global_update_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    walk_forward_run_id = Column(
        Integer,
        ForeignKey("walk_forward_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    calibration_run_id = Column(
        Integer,
        ForeignKey("calibration_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    message = Column(Text, nullable=True)
    report_json = Column(Text, nullable=True)
    email_status = Column(String(32), nullable=True)
    email_error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
