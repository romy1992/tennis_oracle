from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.db.session import get_db
from backend.src.app.ml.model_versioning import ModelVersion
from backend.src.app.schemas.betting_slips import (
    BettingSlipCalendarResponse,
    BettingSlipsDailyResponse,
    BettingSlipsRefreshResponse,
    BettingSlipStatsResponse,
)
from backend.src.app.services.betting_slips import (
    compute_betting_slip_stats,
    get_betting_slip_calendar,
    get_daily_betting_slips,
    refresh_betting_slips,
)


router = APIRouter(prefix="/betting-slips", tags=["betting-slips"])


@router.get("/daily", response_model=BettingSlipsDailyResponse)
def read_daily_betting_slips(
    slip_date: date | None = Query(default=None, alias="date"),
    model_version: ModelVersion = Query(default="v2"),
    model_name: str | None = Query(default=None),
    stake: float = Query(default=10.0, ge=0.01),
    slip_count: int = Query(default=5, ge=1, le=5),
    picks_per_slip: int = Query(default=5, ge=4, le=5),
    regenerate: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> BettingSlipsDailyResponse:
    try:
        return get_daily_betting_slips(
            db=db,
            slip_date=slip_date,
            model_version=model_version,
            model_name=model_name,
            stake=stake,
            slip_count=slip_count,
            picks_per_slip=picks_per_slip,
            regenerate=regenerate,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for betting slips is not available.",
        ) from exc


@router.get("/calendar", response_model=BettingSlipCalendarResponse)
def read_betting_slip_calendar(
    model_version: ModelVersion = Query(default="v2"),
    model_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> BettingSlipCalendarResponse:
    try:
        return get_betting_slip_calendar(
            db=db,
            model_version=model_version,
            model_name=model_name,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for betting slip calendar is not available.",
        ) from exc


@router.post("/refresh", response_model=BettingSlipsRefreshResponse)
def refresh_daily_betting_slips(
    slip_date: date | None = Query(default=None, alias="date"),
    model_version: ModelVersion = Query(default="v2"),
    model_name: str | None = Query(default=None),
    stake: float = Query(default=10.0, ge=0.01),
    days_back: int = Query(default=1, ge=0, le=14),
    db: Session = Depends(get_db),
) -> BettingSlipsRefreshResponse:
    try:
        return refresh_betting_slips(
            db=db,
            slip_date=slip_date,
            model_version=model_version,
            model_name=model_name,
            stake=stake,
            days_back=days_back,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database not available for betting slip refresh.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/stats", response_model=BettingSlipStatsResponse)
def read_betting_slip_stats(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    model_version: ModelVersion = Query(default="v2"),
    stake: float = Query(default=10.0, ge=0.01),
    all_time: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> BettingSlipStatsResponse:
    if (
        not all_time
        and from_date is not None
        and to_date is not None
        and to_date < from_date
    ):
        raise HTTPException(status_code=400, detail="to_date must be >= from_date.")
    try:
        return compute_betting_slip_stats(
            db=db,
            model_version=model_version,
            from_date=from_date,
            to_date=to_date,
            stake=stake,
            all_time=all_time,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for betting slips is not available.",
        ) from exc
