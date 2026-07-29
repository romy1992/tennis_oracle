"""Admin walk-forward validation API."""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.core.config import get_settings
from backend.src.app.db.session import get_db
from backend.src.app.schemas.walk_forward import (
    WalkForwardCancelResponse,
    WalkForwardRunListResponse,
    WalkForwardRunRead,
    WalkForwardTriggerRequest,
    WalkForwardTriggerResponse,
)
from backend.src.app.services.walk_forward import (
    cancel_walk_forward_run,
    get_latest_walk_forward_run,
    get_walk_forward_run,
    list_walk_forward_runs,
    run_to_list_item,
    run_to_read,
    start_walk_forward_run,
)

router = APIRouter(
    prefix="/walk-forward",
    tags=["walk-forward"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=WalkForwardRunListResponse)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> WalkForwardRunListResponse:
    rows, total = list_walk_forward_runs(db, limit=limit, offset=offset)
    return WalkForwardRunListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[run_to_list_item(row) for row in rows],
    )


@router.get("/latest", response_model=WalkForwardRunRead)
def read_latest_run(db: Session = Depends(get_db)) -> WalkForwardRunRead:
    row = get_latest_walk_forward_run(db)
    if row is None:
        raise HTTPException(status_code=404, detail="Nessuna run walk-forward disponibile")
    return run_to_read(row)


@router.post("/runs", response_model=WalkForwardTriggerResponse)
def trigger_run(
    body: WalkForwardTriggerRequest = Body(default_factory=WalkForwardTriggerRequest),
    db: Session = Depends(get_db),
) -> WalkForwardTriggerResponse:
    """Start a walk-forward validation (background by default). Does not change public model."""
    try:
        run, started, message = start_walk_forward_run(
            db,
            request=body,
            settings=get_settings(),
            origin="manual",
            created_by="admin_api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return WalkForwardTriggerResponse(
        run=run_to_read(run),
        started=started,
        message=message,
    )


@router.get("/runs/{run_id}", response_model=WalkForwardRunRead)
def read_run(run_id: int, db: Session = Depends(get_db)) -> WalkForwardRunRead:
    row = get_walk_forward_run(db, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run non trovata")
    return run_to_read(row)


@router.post("/runs/{run_id}/cancel", response_model=WalkForwardCancelResponse)
def cancel_run(run_id: int, db: Session = Depends(get_db)) -> WalkForwardCancelResponse:
    ok, message = cancel_walk_forward_run(db, run_id)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    row = get_walk_forward_run(db, run_id)
    assert row is not None
    return WalkForwardCancelResponse(run_id=row.id, status=row.status, message=message)
