from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.schemas.telegram_analytics import (
    TelegramBotEventsResponse,
    TelegramBotStatsResponse,
)
from backend.src.app.services.telegram_analytics import (
    compute_telegram_stats,
    list_telegram_events,
)


router = APIRouter(
    prefix="/telegram",
    tags=["telegram"],
    dependencies=[Depends(require_admin)],
)


@router.get("/events", response_model=TelegramBotEventsResponse)
def read_telegram_events(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    action: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    username: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> TelegramBotEventsResponse:
    try:
        return list_telegram_events(
            db,
            from_date=from_date,
            to_date=to_date,
            action=action,
            user_id=user_id,
            username=username,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram bot events is not available.",
        ) from exc


@router.get("/stats", response_model=TelegramBotStatsResponse)
def read_telegram_stats(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> TelegramBotStatsResponse:
    try:
        return compute_telegram_stats(
            db,
            from_date=from_date,
            to_date=to_date,
            days=days,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram bot events is not available.",
        ) from exc
