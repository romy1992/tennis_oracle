from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.schemas.published_prediction import (
    InitialStatus,
    PredictionMarket,
    PublishedLiveStatsSummary,
    PublishedPredictionCorrection,
    PublishedPredictionCreate,
    PublishedPredictionListResponse,
    PublishedPredictionRead,
    PublishedPredictionVersionChainResponse,
)
from backend.src.app.services.published_live_stats import compute_published_live_stats
from backend.src.app.services.published_predictions import (
    PublishedPredictionError,
    correct_published_prediction,
    get_published_prediction,
    list_publication_versions,
    list_published_predictions,
    publish_prediction,
)


router = APIRouter(
    prefix="/published-predictions",
    tags=["published-predictions"],
    dependencies=[Depends(require_admin)],
)


def _raise_domain(exc: PublishedPredictionError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("", response_model=PublishedPredictionRead, status_code=201)
def create_published_prediction(
    payload: PublishedPredictionCreate,
    db: Session = Depends(get_db),
) -> PublishedPredictionRead:
    try:
        return publish_prediction(db, payload)
    except PublishedPredictionError as exc:
        _raise_domain(exc)


@router.get("", response_model=PublishedPredictionListResponse)
def read_published_predictions(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    event_key: int | None = Query(default=None),
    model_version: str | None = Query(default=None),
    model_name: str | None = Query(default=None),
    publication_source: str | None = Query(default=None),
    latest_only: bool = Query(default=True),
    market: PredictionMarket | None = Query(default=None),
    include_archived: bool = Query(default=True),
    official_only: bool = Query(default=False),
    initial_status: InitialStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PublishedPredictionListResponse:
    return list_published_predictions(
        db,
        from_date=from_date,
        to_date=to_date,
        event_key=event_key,
        model_version=model_version,
        model_name=model_name,
        publication_source=publication_source,
        latest_only=latest_only,
        market=market,
        include_archived=include_archived,
        official_only=official_only,
        initial_status=initial_status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/by-publication/{publication_id}",
    response_model=PublishedPredictionVersionChainResponse,
)
def read_publication_versions(
    publication_id: str,
    db: Session = Depends(get_db),
) -> PublishedPredictionVersionChainResponse:
    try:
        return list_publication_versions(db, publication_id)
    except PublishedPredictionError as exc:
        _raise_domain(exc)


@router.get("/stats", response_model=PublishedLiveStatsSummary)
def read_published_live_stats(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    event_date_from: date | None = Query(default=None),
    event_date_to: date | None = Query(default=None),
    model_version: str | None = Query(default=None),
    model_name: str | None = Query(default=None),
    publication_source: str | None = Query(default=None),
    tournament_name: str | None = Query(default=None),
    surface: str | None = Query(default=None),
    odds_band: str | None = Query(default=None),
    latest_only: bool = Query(default=True),
    market: PredictionMarket | None = Query(default=None),
    include_archived: bool = Query(default=True),
    official_only: bool = Query(default=False),
    initial_status: InitialStatus | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PublishedLiveStatsSummary:
    """Live tipbook KPIs from the immutable published ledger only."""
    try:
        return compute_published_live_stats(
            db,
            from_date=from_date,
            to_date=to_date,
            event_date_from=event_date_from,
            event_date_to=event_date_to,
            model_version=model_version,
            model_name=model_name,
            publication_source=publication_source,
            tournament_name=tournament_name,
            surface=surface,
            odds_band=odds_band,
            latest_only=latest_only,
            market=market,
            include_archived=include_archived,
            official_only=official_only,
            initial_status=initial_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{prediction_id}", response_model=PublishedPredictionRead)
def read_published_prediction(
    prediction_id: int,
    db: Session = Depends(get_db),
) -> PublishedPredictionRead:
    try:
        return get_published_prediction(db, prediction_id)
    except PublishedPredictionError as exc:
        _raise_domain(exc)


@router.post(
    "/{prediction_id}/corrections",
    response_model=PublishedPredictionRead,
    status_code=201,
)
def create_published_prediction_correction(
    prediction_id: int,
    payload: PublishedPredictionCorrection,
    db: Session = Depends(get_db),
) -> PublishedPredictionRead:
    try:
        return correct_published_prediction(
            db,
            previous_id=prediction_id,
            payload=payload,
        )
    except PublishedPredictionError as exc:
        _raise_domain(exc)
