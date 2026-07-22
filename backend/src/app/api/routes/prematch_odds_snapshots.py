from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.schemas.prematch_odds_snapshot import (
    PrematchOddsSnapshotCreate,
    PrematchOddsSnapshotFromPayload,
    PrematchOddsSnapshotIngestResponse,
    PrematchOddsSnapshotListResponse,
    PrematchOddsSnapshotRead,
)
from backend.src.app.services.prematch_odds_snapshots import (
    PrematchOddsSnapshotError,
    get_snapshot,
    list_snapshots,
    record_odds_from_stored_fixture,
    record_odds_payload,
    record_snapshot,
)


router = APIRouter(
    prefix="/prematch-odds-snapshots",
    tags=["prematch-odds-snapshots"],
    dependencies=[Depends(require_admin)],
)


def _raise_domain(exc: PrematchOddsSnapshotError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("", response_model=PrematchOddsSnapshotRead, status_code=201)
def create_prematch_odds_snapshot(
    payload: PrematchOddsSnapshotCreate,
    db: Session = Depends(get_db),
) -> PrematchOddsSnapshotRead:
    try:
        created = record_snapshot(db, payload)
    except PrematchOddsSnapshotError as exc:
        _raise_domain(exc)
    if created is None:
        raise HTTPException(
            status_code=409,
            detail="Duplicate or unchanged odds detection; nothing inserted.",
        )
    return created


@router.post(
    "/from-payload",
    response_model=PrematchOddsSnapshotIngestResponse,
    status_code=201,
)
def create_prematch_odds_snapshots_from_payload(
    payload: PrematchOddsSnapshotFromPayload,
    db: Session = Depends(get_db),
) -> PrematchOddsSnapshotIngestResponse:
    try:
        return record_odds_payload(db, payload)
    except PrematchOddsSnapshotError as exc:
        _raise_domain(exc)


@router.post(
    "/from-fixture/{event_key}",
    response_model=PrematchOddsSnapshotIngestResponse,
    status_code=201,
)
def create_prematch_odds_snapshots_from_fixture(
    event_key: int,
    db: Session = Depends(get_db),
) -> PrematchOddsSnapshotIngestResponse:
    try:
        return record_odds_from_stored_fixture(db, event_key, source="admin_api")
    except PrematchOddsSnapshotError as exc:
        _raise_domain(exc)


@router.get("", response_model=PrematchOddsSnapshotListResponse)
def read_prematch_odds_snapshots(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    event_key: int | None = Query(default=None),
    bookmaker: str | None = Query(default=None),
    selection: str | None = Query(default=None),
    snapshot_type: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PrematchOddsSnapshotListResponse:
    return list_snapshots(
        db,
        event_key=event_key,
        bookmaker=bookmaker,
        selection=selection,
        snapshot_type=snapshot_type,
        source=source,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


@router.get("/{snapshot_id}", response_model=PrematchOddsSnapshotRead)
def read_prematch_odds_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
) -> PrematchOddsSnapshotRead:
    try:
        return get_snapshot(db, snapshot_id)
    except PrematchOddsSnapshotError as exc:
        _raise_domain(exc)
