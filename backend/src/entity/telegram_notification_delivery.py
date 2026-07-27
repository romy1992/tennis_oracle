"""Outbound Telegram notification delivery ledger (dedupe + retries + errors)."""

from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, String, Text

from backend.src.entity.base import Base


class TelegramNotificationDelivery(Base):
    """One outbound notification attempt group per user/kind/day (dedupe_key unique)."""

    __tablename__ = "telegram_notification_delivery"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dedupe_key = Column(String(191), nullable=False, unique=True)
    kind = Column(String(64), nullable=False, index=True)
    content_date = Column(Date, nullable=False, index=True)
    telegram_user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=True)
    # pending | sent | failed | skipped
    status = Column(String(32), nullable=False, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    telegram_message_id = Column(BigInteger, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    sent_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
