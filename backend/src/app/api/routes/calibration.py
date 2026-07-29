"""Admin probability calibration API."""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.core.config import get_settings
from backend.src.app.db.session import get_db
from backend.src.app.schemas.calibration import (
    CalibrationCancelResponse,
    CalibrationRunListResponse,
    CalibrationRunRead,
    CalibrationTriggerRequest,
    CalibrationTriggerResponse,
)
from backend.src.app.services.calibration import (
    cancel_calibration_run,
    get_calibration_run,
    get_latest_calibration_run,
    list_calibration_runs,
    run_to_list_item,
    run_to_read,
    start_calibration_run,
)

router = APIRouter(
    prefix="/calibration",
    tags=["calibration"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=CalibrationRunListResponse)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> CalibrationRunListResponse:
    rows, total = list_calibration_runs(db, limit=limit, offset=offset)
    return CalibrationRunListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[run_to_list_item(row) for row in rows],
    )


@router.get("/latest", response_model=CalibrationRunRead)
def read_latest_run(db: Session = Depends(get_db)) -> CalibrationRunRead:
    row = get_latest_calibration_run(db)
    if row is None:
        raise HTTPException(status_code=404, detail="Nessuna run calibrazione disponibile")
    return run_to_read(row)


@router.post("/runs", response_model=CalibrationTriggerResponse)
def trigger_run(
    body: CalibrationTriggerRequest = Body(default_factory=CalibrationTriggerRequest),
    db: Session = Depends(get_db),
) -> CalibrationTriggerResponse:
    """Start calibration analysis (background by default). Does not change public model."""
    try:
        run, started, message = start_calibration_run(
            db,
            request=body,
            settings=get_settings(),
            origin="manual",
            created_by="admin_api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CalibrationTriggerResponse(
        run=run_to_read(run),
        started=started,
        message=message,
    )


@router.get("/runs/{run_id}", response_model=CalibrationRunRead)
def read_run(run_id: int, db: Session = Depends(get_db)) -> CalibrationRunRead:
    row = get_calibration_run(db, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run non trovata")
    return run_to_read(row)


@router.post("/runs/{run_id}/cancel", response_model=CalibrationCancelResponse)
def cancel_run(run_id: int, db: Session = Depends(get_db)) -> CalibrationCancelResponse:
    ok, message = cancel_calibration_run(db, run_id)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    row = get_calibration_run(db, run_id)
    assert row is not None
    return CalibrationCancelResponse(run_id=row.id, status=row.status, message=message)
