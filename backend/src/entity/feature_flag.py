"""Feature flags toggled by admins from dashboard and consumed by runtime services."""

from sqlalchemy import Boolean, Column, DateTime, String

from backend.src.entity.base import Base


class FeatureFlag(Base):
    """System-wide feature switch persisted in DB."""

    __tablename__ = "feature_flag"

    key = Column(String(64), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, nullable=False, index=True)
    updated_by = Column(String(150), nullable=True)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


