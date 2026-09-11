"""Admin-editable schedules for background jobs."""

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from backend.src.entity.base import Base


class ScheduledJobSetting(Base):
    """Database overlay for a catalogued scheduler job."""

    __tablename__ = "scheduled_job_setting"

    job_key = Column(String(64), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    schedule_kind = Column(String(32), nullable=False)
    clock_time = Column(String(5), nullable=True)
    weekday = Column(Integer, nullable=True)
    interval_seconds = Column(Integer, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(32), nullable=True)
    updated_at = Column(DateTime, nullable=False, index=True)
    updated_by = Column(String(150), nullable=True)

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }
