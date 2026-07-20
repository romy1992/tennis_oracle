from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.src.app.db.session import SessionLocal
from backend.src.app.schemas.telegram_analytics import (
    TelegramBotActionCount,
    TelegramBotDayCount,
    TelegramBotEventRead,
    TelegramBotEventsResponse,
    TelegramBotStatsResponse,
)
from backend.src.entity.telegram_bot_event import TelegramBotEvent

logger = logging.getLogger(__name__)

ROME_TZ = ZoneInfo("Europe/Rome")
RAW_TEXT_MAX_LEN = 500
ERROR_MESSAGE_MAX_LEN = 500


def _truncate(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def record_telegram_event(
    *,
    db: Session,
    event_type: str,
    action: str,
    telegram_user_id: int | None = None,
    chat_id: int | None = None,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    raw_text: str | None = None,
    success: bool | None = True,
    error_message: str | None = None,
    created_at: datetime | None = None,
) -> TelegramBotEvent:
    row = TelegramBotEvent(
        created_at=created_at or datetime.now(),
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        username=_truncate(username, 255),
        first_name=_truncate(first_name, 255),
        last_name=_truncate(last_name, 255),
        event_type=event_type,
        action=(action or "unknown")[:255],
        raw_text=_truncate(raw_text, RAW_TEXT_MAX_LEN),
        success=success,
        error_message=_truncate(error_message, ERROR_MESSAGE_MAX_LEN),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def record_telegram_event_safe(**kwargs) -> None:
    """Persist an event without raising; never break the bot."""
    db = None
    try:
        db = SessionLocal()
        record_telegram_event(db=db, **kwargs)
    except Exception:
        logger.warning("Impossibile salvare evento Telegram analytics", exc_info=True)
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        if db is not None:
            db.close()


def _apply_event_filters(
    stmt,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    action: str | None = None,
    user_id: int | None = None,
    username: str | None = None,
    event_type: str | None = None,
):
    if from_date is not None:
        stmt = stmt.where(TelegramBotEvent.created_at >= datetime.combine(from_date, time.min))
    if to_date is not None:
        stmt = stmt.where(
            TelegramBotEvent.created_at < datetime.combine(to_date + timedelta(days=1), time.min)
        )
    if action:
        stmt = stmt.where(TelegramBotEvent.action == action)
    if user_id is not None:
        stmt = stmt.where(TelegramBotEvent.telegram_user_id == user_id)
    if username:
        stmt = stmt.where(TelegramBotEvent.username.ilike(f"%{username.strip().lstrip('@')}%"))
    if event_type:
        stmt = stmt.where(TelegramBotEvent.event_type == event_type)
    return stmt


def list_telegram_events(
    db: Session,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    action: str | None = None,
    user_id: int | None = None,
    username: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> TelegramBotEventsResponse:
    base = select(TelegramBotEvent)
    base = _apply_event_filters(
        base,
        from_date=from_date,
        to_date=to_date,
        action=action,
        user_id=user_id,
        username=username,
        event_type=event_type,
    )

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(TelegramBotEvent.created_at.desc(), TelegramBotEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return TelegramBotEventsResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[TelegramBotEventRead.model_validate(row) for row in rows],
    )


def compute_telegram_stats(
    db: Session,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    days: int = 30,
) -> TelegramBotStatsResponse:
    today = datetime.now(ROME_TZ).date()
    range_from = from_date or (today - timedelta(days=max(days - 1, 0)))
    range_to = to_date or today

    filtered = _apply_event_filters(
        select(TelegramBotEvent),
        from_date=range_from,
        to_date=range_to,
    )
    filtered_subq = filtered.subquery()

    total_events = db.scalar(select(func.count()).select_from(filtered_subq)) or 0
    unique_users = (
        db.scalar(
            select(func.count(func.distinct(filtered_subq.c.telegram_user_id))).where(
                filtered_subq.c.telegram_user_id.is_not(None)
            )
        )
        or 0
    )

    today_start = datetime.combine(today, time.min)
    tomorrow_start = datetime.combine(today + timedelta(days=1), time.min)
    events_today = (
        db.scalar(
            select(func.count())
            .select_from(TelegramBotEvent)
            .where(
                TelegramBotEvent.created_at >= today_start,
                TelegramBotEvent.created_at < tomorrow_start,
            )
        )
        or 0
    )

    by_action_rows = db.execute(
        select(filtered_subq.c.action, func.count().label("count"))
        .group_by(filtered_subq.c.action)
        .order_by(func.count().desc(), filtered_subq.c.action.asc())
    ).all()
    by_action = [TelegramBotActionCount(action=row.action, count=row.count) for row in by_action_rows]
    top_action = by_action[0].action if by_action else None

    day_expr = func.date(TelegramBotEvent.created_at)
    by_day_rows = db.execute(
        select(day_expr.label("day"), func.count().label("count"))
        .where(
            TelegramBotEvent.created_at >= datetime.combine(range_from, time.min),
            TelegramBotEvent.created_at < datetime.combine(range_to + timedelta(days=1), time.min),
        )
        .group_by(day_expr)
        .order_by(day_expr.asc())
    ).all()

    counts_by_day = {}
    for row in by_day_rows:
        day_value = row.day
        if isinstance(day_value, datetime):
            day_value = day_value.date()
        elif isinstance(day_value, str):
            day_value = date.fromisoformat(day_value)
        counts_by_day[day_value] = row.count

    by_day: list[TelegramBotDayCount] = []
    cursor = range_from
    while cursor <= range_to:
        by_day.append(TelegramBotDayCount(day=cursor, count=counts_by_day.get(cursor, 0)))
        cursor += timedelta(days=1)

    return TelegramBotStatsResponse(
        total_events=total_events,
        unique_users=unique_users,
        events_today=events_today,
        top_action=top_action,
        by_action=by_action,
        by_day=by_day,
    )
