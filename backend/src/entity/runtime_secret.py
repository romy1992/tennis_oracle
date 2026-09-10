"""Runtime integration settings managed through the admin dashboard."""

from sqlalchemy import Column, DateTime, String, Text

from backend.src.entity.base import Base


class RuntimeSecret(Base):
    """Database override for an external integration credential."""

    __tablename__ = "runtime_secret"

    key = Column(String(128), primary_key=True)
    encrypted_value = Column(Text, nullable=False)
    encryption_scheme = Column(String(32), nullable=False, default="database-v1")
    fingerprint = Column(String(32), nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False, index=True)
    updated_by = Column(String(150), nullable=False)

    def to_dict(self):
        return {
            "key": self.key,
            "encryption_scheme": self.encryption_scheme,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
        }
