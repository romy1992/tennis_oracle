"""Administrative audit log for manual dashboard operations."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.src.entity.base import Base


class AdminAuditLog(Base):
    """Tracks sensitive manual actions executed by admin users."""

    __tablename__ = "admin_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_user_id = Column(Integer, ForeignKey("admin_user.id"), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    target_type = Column(String(64), nullable=False, index=True)
    target_id = Column(String(128), nullable=True, index=True)
    description = Column(String(255), nullable=True)
    context_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, index=True)

    admin_user = relationship("AdminUser", back_populates="audit_logs")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


