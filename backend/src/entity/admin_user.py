"""Administrative users for dashboard and privileged API access."""

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from backend.src.entity.base import Base


class AdminUser(Base):
    """Local admin account (password stored as bcrypt hash)."""

    __tablename__ = "admin_user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(150), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
