"""Fixed-window rate-limit counters shared across API instances and the Telegram bot."""

from sqlalchemy import Column, DateTime, Integer, String

from backend.src.entity.base import Base


class RateLimitBucket(Base):
    """One row per rate-limit key; hit_count resets when the window rolls over."""

    __tablename__ = "rate_limit_bucket"

    bucket_key = Column(String(255), primary_key=True)
    window_start = Column(DateTime, nullable=False)
    hit_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False)
