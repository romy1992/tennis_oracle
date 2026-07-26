"""Distributed named locks for pipeline jobs (shared across API / CLI workers)."""

from sqlalchemy import Column, DateTime, Integer, String

from backend.src.entity.base import Base


class PipelineLock(Base):
    """Single-row-per-name lease used to prevent concurrent pipeline executions."""

    __tablename__ = "pipeline_lock"

    name = Column(String(64), primary_key=True)
    owner_token = Column(String(64), nullable=True)
    run_id = Column(Integer, nullable=True)
    acquired_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
