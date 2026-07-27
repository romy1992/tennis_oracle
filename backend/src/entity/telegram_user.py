"""Telegram beta end-users (whitelist / access control)."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String

from backend.src.entity.base import Base


class TelegramUser(Base):
    """Registered Telegram beta user with access status and invite metadata."""

    __tablename__ = "telegram_user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(BigInteger, nullable=False, unique=True, index=True)
    # Private chat id for proactive DM (usually equals telegram_user_id).
    chat_id = Column(BigInteger, nullable=True, index=True)
    username = Column(String(255), nullable=True, index=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    # invited | active | suspended | blocked
    status = Column(String(32), nullable=False, default="invited", index=True)
    invite_origin = Column(String(255), nullable=True)
    first_access_at = Column(DateTime, nullable=False)
    last_access_at = Column(DateTime, nullable=False)
    terms_accepted = Column(Boolean, nullable=False, default=False)
    terms_accepted_at = Column(DateTime, nullable=True)
    terms_version = Column(String(64), nullable=True)
    # Push notification preferences (bot /notifiche). Master switch + per-kind.
    notifications_enabled = Column(Boolean, nullable=False, default=True)
    notify_predictions = Column(Boolean, nullable=False, default=True)
    notify_results = Column(Boolean, nullable=False, default=True)
    notify_empty_day = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
