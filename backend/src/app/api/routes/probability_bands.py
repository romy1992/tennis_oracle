"""Probability and edge band performance analysis (ML-03)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.ml.training.calibration import CalibrationMethod
from backend.src.app.schemas.probability_bands import (
    AnalysisSource,
    BandDimension,
    ProbabilityBandAnalysisRead,
)
from backend.src.app.services.probability_band_stats import compute_probability_band_analysis


router = APIRouter(
    prefix="/probability-bands",
    tags=["probability-bands"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=ProbabilityBandAnalysisRead)
def read_probability_band_analysis(
    source: AnalysisSource = Query(..., description="live | walk_forward | backtest"),
    band_dimension: BandDimension = Query(default="probability"),
    probability_kind: CalibrationMethod = Query(default="raw"),
    model_version: str | None = Query(default=None),
    model_name: str | None = Query(default=None),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    event_date_from: date | None = Query(default=None),
    event_date_to: date | None = Query(default=None),
    publication_source: str | None = Query(default=None),
    tournament_name: str | None = Query(default=None),
    surface: str | None = Query(default=None),
    odds_band: str | None = Query(default=None),
    latest_only: bool = Query(default=True),
    market: str | None = Query(
        default=None,
        description="Solo source=live: match_winner | first_set_winner | over_under_games "
        "(default match_winner). Ignorato su walk-forward/backtest.",
    ),
    include_archived: bool = Query(
        default=False,
        description="Solo source=live: include tip match-winner di versioni archiviate.",
    ),
    n_bins: int | None = Query(default=None, ge=2, le=50),
    min_bin_samples: int | None = Query(default=None, ge=1),
    include_comparison: bool = Query(
        default=False,
        description="Confronto raw/platt/isotonic (solo OOS, band_dimension=probability).",
    ),
    group_by_fold: bool = Query(default=False),
    group_by_period: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> ProbabilityBandAnalysisRead:
    try:
        return compute_probability_band_analysis(
            db,
            source=source,
            band_dimension=band_dimension,
            probability_kind=probability_kind,
            model_version=model_version,
            model_name=model_name,
            from_date=from_date,
            to_date=to_date,
            event_date_from=event_date_from,
            event_date_to=event_date_to,
            publication_source=publication_source,
            tournament_name=tournament_name,
            surface=surface,
            odds_band=odds_band,
            latest_only=latest_only,
            market=market,
            include_archived=include_archived,
            n_bins=n_bins,
            min_bin_samples=min_bin_samples,
            include_comparison=include_comparison,
            group_by_fold=group_by_fold,
            group_by_period=group_by_period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
