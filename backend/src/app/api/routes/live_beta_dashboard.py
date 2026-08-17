"""Admin live-beta dashboard API."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.schemas.live_beta_dashboard import LiveBetaDashboardResponse
from backend.src.app.schemas.published_prediction import PredictionMarket
from backend.src.app.services.live_beta_dashboard import compute_live_beta_dashboard


router = APIRouter(
    prefix="/live-beta-dashboard",
    tags=["live-beta-dashboard"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=LiveBetaDashboardResponse)
def read_live_beta_dashboard(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    model_version: str | None = Query(default=None),
    model_name: str | None = Query(default=None),
    tournament_name: str | None = Query(default=None),
    surface: str | None = Query(default=None),
    odds_band: str | None = Query(default=None),
    latest_only: bool = Query(default=True),
    tip_limit: int = Query(default=25, ge=1, le=100),
    market: PredictionMarket = Query(default="match_winner"),
    include_archived: bool = Query(default=False),
    official_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> LiveBetaDashboardResponse:
    """Aggregate LIVE beta ops view (pipeline, tipbook, bot, completeness, errors)."""
    try:
        return compute_live_beta_dashboard(
            db,
            from_date=from_date,
            to_date=to_date,
            model_version=model_version,
            model_name=model_name,
            tournament_name=tournament_name,
            surface=surface,
            odds_band=odds_band,
            latest_only=latest_only,
            tip_limit=tip_limit,
            market=market,
            include_archived=include_archived,
            official_only=official_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
