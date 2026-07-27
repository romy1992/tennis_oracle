"""Persisted weekly beta KPIs (snapshot + WoW comparison)."""

from sqlalchemy import Column, Date, DateTime, Integer, String, Text, UniqueConstraint

from backend.src.entity.base import Base


class WeeklyBetaReport(Base):
    """One immutable-ish weekly beta report for a Monday–Sunday Rome window."""

    __tablename__ = "weekly_beta_report"
    __table_args__ = (
        UniqueConstraint("week_start", "week_end", name="uq_weekly_beta_report_week"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(Date, nullable=False, index=True)
    week_end = Column(Date, nullable=False, index=True)
    # ISO week label e.g. 2026-W30
    week_label = Column(String(16), nullable=False, index=True)
    # Full computed payload (metrics + previous week + deltas).
    payload_json = Column(Text, nullable=False)
    # pending | sent | skipped | failed
    telegram_status = Column(String(32), nullable=False, default="pending")
    telegram_error = Column(Text, nullable=True)
    telegram_sent_at = Column(DateTime, nullable=True)
    generated_at = Column(DateTime, nullable=False)
    generated_by = Column(String(64), nullable=False, default="job")

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
