"""Persisted Telegram bot user interactions (admin analytics)."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text

from backend.src.entity.base import Base


class TelegramBotEvent(Base):
    """One user interaction with the Telegram bot (command, message, or callback)."""

    __tablename__ = "telegram_bot_event"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, index=True)
    telegram_user_id = Column(BigInteger, nullable=True, index=True)
    chat_id = Column(BigInteger, nullable=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    event_type = Column(String, nullable=False)  # command | message | callback
    action = Column(String, nullable=False, index=True)
    raw_text = Column(String, nullable=True)
    success = Column(Boolean, nullable=True)
    error_message = Column(Text, nullable=True)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
