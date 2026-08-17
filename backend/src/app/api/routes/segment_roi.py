"""Segment ROI performance analysis (ML-04)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.schemas.segment_roi import (
    AnalysisSource,
    SegmentDimension,
    SegmentRoiAnalysisRead,
)
from backend.src.app.services.segment_roi_stats import compute_segment_roi_analysis


router = APIRouter(
    prefix="/segment-roi",
    tags=["segment-roi"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=SegmentRoiAnalysisRead)
def read_segment_roi_analysis(
    source: AnalysisSource = Query(..., description="live | walk_forward | backtest"),
    segment_dimension: SegmentDimension = Query(default="surface"),
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
    min_segment_samples: int | None = Query(default=None, ge=1),
    group_by_fold: bool = Query(default=False),
    group_by_period: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> SegmentRoiAnalysisRead:
    try:
        return compute_segment_roi_analysis(
            db,
            source=source,
            segment_dimension=segment_dimension,
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
            min_segment_samples=min_segment_samples,
            group_by_fold=group_by_fold,
            group_by_period=group_by_period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
