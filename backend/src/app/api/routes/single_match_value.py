from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.db.session import get_db
from backend.src.app.ml.model_versioning import ModelVersion
from backend.src.app.schemas.single_match_value import SingleMatchValueResponse
from backend.src.app.services.predictions import FixturePredictionStatus, PredictionOutcome
from backend.src.app.services.single_match_value import get_single_match_value_analysis

router = APIRouter(prefix="/single-match-value", tags=["single-match-value"])


@router.get("", response_model=SingleMatchValueResponse)
def read_single_match_value_analysis(
    model_version: ModelVersion = Query(default="v2"),
    model_name: str | None = Query(default=None),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: FixturePredictionStatus = Query(default="upcoming"),
    outcome: PredictionOutcome = Query(default="all"),
    player: str | None = Query(default=None, min_length=1, max_length=100),
    min_edge_percent: float = Query(default=3.0, ge=0.0, le=100.0),
    db: Session = Depends(get_db),
) -> SingleMatchValueResponse:
    try:
        return get_single_match_value_analysis(
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
            min_edge_percent=min_edge_percent,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for single match value analysis is not available.",
        ) from exc
