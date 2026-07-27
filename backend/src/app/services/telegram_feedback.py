"""Telegram feedback inbox: create from bot, list/update status for admin."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.src.app.db.session import SessionLocal
from backend.src.app.schemas.telegram_feedback import (
    TelegramFeedbackCreate,
    TelegramFeedbackListResponse,
    TelegramFeedbackRead,
    TelegramFeedbackStatusUpdate,
)
from backend.src.entity.telegram_feedback import TelegramFeedback

logger = logging.getLogger(__name__)

CATEGORIES = frozenset({"bug", "content", "ux", "feature", "access", "other"})
STATUSES = frozenset({"new", "reviewing", "resolved", "rejected"})
USERNAME_MAX = 255
NAME_MAX = 255
MESSAGE_MAX = 2000


class TelegramFeedbackError(Exception):
    """Domain error for Telegram feedback."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _truncate(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _to_read(row: TelegramFeedback) -> TelegramFeedbackRead:
    return TelegramFeedbackRead.model_validate(row)


def create_telegram_feedback(
    db: Session,
    payload: TelegramFeedbackCreate,
) -> TelegramFeedbackRead:
    category = payload.category.strip().lower()
    if category not in CATEGORIES:
        raise TelegramFeedbackError(f"Categoria non valida: {payload.category}", status_code=400)
    if payload.rating < 1 or payload.rating > 5:
        raise TelegramFeedbackError("La valutazione deve essere tra 1 e 5.", status_code=400)

    message = (payload.message or "").strip()
    if not message:
        raise TelegramFeedbackError("Il messaggio non può essere vuoto.", status_code=400)
    if len(message) > MESSAGE_MAX:
        message = message[: MESSAGE_MAX - 1] + "…"

    now = _utc_now_naive()
    row = TelegramFeedback(
        telegram_user_id=payload.telegram_user_id,
        username=_truncate(payload.username, USERNAME_MAX),
        first_name=_truncate(payload.first_name, NAME_MAX),
        last_name=_truncate(payload.last_name, NAME_MAX),
        category=category,
        rating=payload.rating,
        message=message,
        status="new",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_read(row)


def create_telegram_feedback_safe(
    *,
    telegram_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    category: str,
    rating: int,
    message: str,
) -> TelegramFeedbackRead | None:
    """Persist feedback from the bot; fail-open (returns None on DB errors)."""
    try:
        with SessionLocal() as session:
            return create_telegram_feedback(
                session,
                TelegramFeedbackCreate(
                    telegram_user_id=telegram_user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    category=category,  # type: ignore[arg-type]
                    rating=rating,
                    message=message,
                ),
            )
    except TelegramFeedbackError:
        raise
    except Exception:
        logger.exception(
            "Failed to persist telegram feedback user_id=%s",
            telegram_user_id,
        )
        return None


def get_telegram_feedback(db: Session, feedback_id: int) -> TelegramFeedback | None:
    return db.get(TelegramFeedback, feedback_id)


def list_telegram_feedback(
    db: Session,
    *,
    q: str | None = None,
    status: str | None = None,
    category: str | None = None,
    telegram_user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> TelegramFeedbackListResponse:
    stmt = select(TelegramFeedback)
    count_stmt = select(func.count()).select_from(TelegramFeedback)

    if telegram_user_id is not None:
        stmt = stmt.where(TelegramFeedback.telegram_user_id == telegram_user_id)
        count_stmt = count_stmt.where(TelegramFeedback.telegram_user_id == telegram_user_id)
    if status:
        cleaned = status.strip().lower()
        if cleaned not in STATUSES:
            raise TelegramFeedbackError(f"Stato non valido: {status}", status_code=400)
        stmt = stmt.where(TelegramFeedback.status == cleaned)
        count_stmt = count_stmt.where(TelegramFeedback.status == cleaned)
    if category:
        cleaned_cat = category.strip().lower()
        if cleaned_cat not in CATEGORIES:
            raise TelegramFeedbackError(f"Categoria non valida: {category}", status_code=400)
        stmt = stmt.where(TelegramFeedback.category == cleaned_cat)
        count_stmt = count_stmt.where(TelegramFeedback.category == cleaned_cat)
    if q:
        needle = q.strip()
        if needle:
            pattern = f"%{needle}%"
            try:
                as_id = int(needle)
            except ValueError:
                as_id = None
            clauses = [
                TelegramFeedback.username.ilike(pattern),
                TelegramFeedback.first_name.ilike(pattern),
                TelegramFeedback.last_name.ilike(pattern),
                TelegramFeedback.message.ilike(pattern),
                TelegramFeedback.category.ilike(pattern),
            ]
            if as_id is not None:
                clauses.append(TelegramFeedback.telegram_user_id == as_id)
                clauses.append(TelegramFeedback.id == as_id)
            stmt = stmt.where(or_(*clauses))
            count_stmt = count_stmt.where(or_(*clauses))

    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        stmt.order_by(TelegramFeedback.created_at.desc(), TelegramFeedback.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return TelegramFeedbackListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_to_read(row) for row in rows],
    )


def update_telegram_feedback_status(
    db: Session,
    feedback_id: int,
    payload: TelegramFeedbackStatusUpdate,
) -> TelegramFeedbackRead:
    row = get_telegram_feedback(db, feedback_id)
    if row is None:
        raise TelegramFeedbackError("Feedback non trovato.", status_code=404)
    new_status = payload.status.strip().lower()
    if new_status not in STATUSES:
        raise TelegramFeedbackError(f"Stato non valido: {payload.status}", status_code=400)
    row.status = new_status
    row.updated_at = _utc_now_naive()
    db.commit()
    db.refresh(row)
    return _to_read(row)
