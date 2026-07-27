"""Admin API for Telegram feedback inbox."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.schemas.telegram_feedback import (
    TelegramFeedbackListResponse,
    TelegramFeedbackRead,
    TelegramFeedbackStatusUpdate,
)
from backend.src.app.services.telegram_feedback import (
    TelegramFeedbackError,
    get_telegram_feedback,
    list_telegram_feedback,
    update_telegram_feedback_status,
)


router = APIRouter(
    prefix="/telegram/feedback",
    tags=["telegram-feedback"],
    dependencies=[Depends(require_admin)],
)


def _raise_domain(exc: TelegramFeedbackError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("", response_model=TelegramFeedbackListResponse)
def search_telegram_feedback(
    q: str | None = Query(default=None, description="Search id, user, message, category"),
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    user_id: int | None = Query(default=None, alias="telegram_user_id"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> TelegramFeedbackListResponse:
    try:
        return list_telegram_feedback(
            db,
            q=q,
            status=status,
            category=category,
            telegram_user_id=user_id,
            limit=limit,
            offset=offset,
        )
    except TelegramFeedbackError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram feedback is not available.",
        ) from exc


@router.get("/{feedback_id}", response_model=TelegramFeedbackRead)
def read_telegram_feedback(
    feedback_id: int,
    db: Session = Depends(get_db),
) -> TelegramFeedbackRead:
    try:
        row = get_telegram_feedback(db, feedback_id)
        if row is None:
            raise TelegramFeedbackError("Feedback non trovato.", status_code=404)
        return TelegramFeedbackRead.model_validate(row)
    except TelegramFeedbackError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram feedback is not available.",
        ) from exc


@router.patch("/{feedback_id}", response_model=TelegramFeedbackRead)
def patch_telegram_feedback_status(
    feedback_id: int,
    payload: TelegramFeedbackStatusUpdate,
    db: Session = Depends(get_db),
) -> TelegramFeedbackRead:
    try:
        return update_telegram_feedback_status(db, feedback_id, payload)
    except TelegramFeedbackError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram feedback is not available.",
        ) from exc
