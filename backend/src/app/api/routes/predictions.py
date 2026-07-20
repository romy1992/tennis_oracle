from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin, require_admin_or_service
from backend.src.app.db.session import get_db
from backend.src.app.ml.model_versioning import ModelVersion
from backend.src.app.schemas.prediction import (
    DailyPredictionStatsResponse,
    FixturesWithPredictionsPage,
    NextFixtureRead,
    PredictionSummaryResponse,
)
from backend.src.app.services.predictions import (
    FixturePredictionStatus,
    PredictionOutcome,
    compute_daily_prediction_stats,
    compute_prediction_summary,
    get_next_fixtures_with_predictions,
    list_next_fixtures,
)


router = APIRouter(prefix="/next-fixtures", tags=["next-fixtures"])
predictions_stats_router = APIRouter(prefix="/predictions/stats", tags=["predictions"])


@router.get("", response_model=list[NextFixtureRead], dependencies=[Depends(require_admin_or_service)])
def read_next_fixtures(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[NextFixtureRead]:
    try:
        return list_next_fixtures(
            db=db,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for next fixtures is not available.",
        ) from exc


@router.get(
    "/predictions",
    response_model=FixturesWithPredictionsPage,
    dependencies=[Depends(require_admin_or_service)],
)
def read_next_fixtures_predictions(
    model_version: ModelVersion = Query(default="v2"),
    model_name: str | None = Query(default=None),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: FixturePredictionStatus = Query(default="upcoming"),
    outcome: PredictionOutcome = Query(default="all"),
    player: str | None = Query(default=None, min_length=1, max_length=100),
    db: Session = Depends(get_db),
) -> FixturesWithPredictionsPage:
    try:
        return get_next_fixtures_with_predictions(
            db=db,
            model_version=model_version,
            model_name=model_name,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
            status=status,
            outcome=outcome,
            player_name=player,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for next fixtures is not available.",
        ) from exc


@predictions_stats_router.get(
    "/daily",
    response_model=DailyPredictionStatsResponse,
    dependencies=[Depends(require_admin)],
)
def read_daily_prediction_stats(
    model_version: ModelVersion = Query(default="v2"),
    model_name: str | None = Query(default=None),
    from_day: int = Query(default=0, ge=0),
    to_day: int | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
) -> DailyPredictionStatsResponse:
    if to_day is not None and to_day < from_day:
        raise HTTPException(status_code=400, detail="to_day must be >= from_day.")
    try:
        return compute_daily_prediction_stats(
            db=db,
            model_version=model_version,
            model_name=model_name,
            from_day=from_day,
            to_day=to_day,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for match predictions is not available.",
        ) from exc


@predictions_stats_router.get(
    "/summary",
    response_model=PredictionSummaryResponse,
    dependencies=[Depends(require_admin_or_service)],
)
def read_prediction_summary(
    model_version: ModelVersion = Query(default="v2"),
    model_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PredictionSummaryResponse:
    try:
        return compute_prediction_summary(db=db, model_version=model_version, model_name=model_name)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for match predictions is not available.",
        ) from exc
