"""Telegram user feedback submissions (in-bot /feedback)."""

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text

from backend.src.entity.base import Base


class TelegramFeedback(Base):
    """Persisted feedback from the Telegram bot conversation."""

    __tablename__ = "telegram_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(BigInteger, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    # bug | content | ux | feature | access | other
    category = Column(String(32), nullable=False, index=True)
    # 1..5
    rating = Column(Integer, nullable=False)
    message = Column(Text, nullable=False)
    # new | reviewing | resolved | rejected
    status = Column(String(32), nullable=False, default="new", index=True)
    created_at = Column(DateTime, nullable=False, index=True)
    updated_at = Column(DateTime, nullable=False)

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
