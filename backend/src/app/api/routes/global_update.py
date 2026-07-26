from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin, require_admin_or_service
from backend.src.app.db.session import get_db
from backend.src.app.schemas.global_update import (
    GlobalUpdateReportRead,
    GlobalUpdateRunRead,
    GlobalUpdateStartRequest,
    GlobalUpdateStartResponse,
    ModelsVersionsResultsResponse,
)
from backend.src.app.services.global_update import (
    build_run_report,
    cancel_global_update,
    get_active_run,
    get_latest_run,
    get_models_versions_results,
    get_run_by_id,
    start_global_update,
)


router = APIRouter(
    prefix="/global-update",
    tags=["global-update"],
    dependencies=[Depends(require_admin)],
)
results_router = APIRouter(prefix="/models-versions", tags=["models-versions"])


def _run_read(run) -> GlobalUpdateRunRead:
    from backend.src.app.services.global_update import _run_to_read_dict

    return GlobalUpdateRunRead.model_validate(_run_to_read_dict(run))


@router.post("", response_model=GlobalUpdateStartResponse)
def trigger_global_update(
    body: GlobalUpdateStartRequest | None = None,
    db: Session = Depends(get_db),
) -> GlobalUpdateStartResponse:
    payload = body or GlobalUpdateStartRequest()
    try:
        run, message = start_global_update(
            db,
            origin="manual",
            force=payload.force,
            days_forward=payload.days_forward,
            days_back_fixtures=payload.days_back_fixtures,
            resume=payload.resume,
            resume_run_id=payload.resume_run_id,
            sync_cloud=payload.sync_cloud,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc

    if run is None:
        active = get_active_run(db)
        if active is not None:
            return GlobalUpdateStartResponse(
                run_id=active.id,
                status=active.status,  # type: ignore[arg-type]
                message=message,
            )
        raise HTTPException(status_code=409, detail=message)

    return GlobalUpdateStartResponse(
        run_id=run.id,
        status=run.status,  # type: ignore[arg-type]
        message=message,
    )


@router.get("/status", response_model=GlobalUpdateRunRead | None)
def read_global_update_status(db: Session = Depends(get_db)) -> GlobalUpdateRunRead | None:
    try:
        run = get_active_run(db) or get_latest_run(db)
        if run is None:
            return None
        return _run_read(run)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc


@router.post("/{run_id}/cancel", response_model=GlobalUpdateStartResponse)
def cancel_global_update_run(
    run_id: int,
    db: Session = Depends(get_db),
) -> GlobalUpdateStartResponse:
    try:
        ok, message = cancel_global_update(db, run_id)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc

    if not ok:
        raise HTTPException(status_code=409, detail=message)

    run = get_run_by_id(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    return GlobalUpdateStartResponse(
        run_id=run.id,
        status=run.status,  # type: ignore[arg-type]
        message=message,
    )


@router.get("/latest", response_model=GlobalUpdateRunRead | None)
def read_latest_global_update(db: Session = Depends(get_db)) -> GlobalUpdateRunRead | None:
    try:
        run = get_latest_run(db)
        if run is None:
            return None
        return _run_read(run)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc


@router.get("/{run_id}", response_model=GlobalUpdateRunRead)
def read_global_update_run(
    run_id: int,
    db: Session = Depends(get_db),
) -> GlobalUpdateRunRead:
    try:
        run = get_run_by_id(db, run_id)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    return _run_read(run)


@router.get("/{run_id}/report", response_model=GlobalUpdateReportRead)
def read_global_update_report(
    run_id: int,
    db: Session = Depends(get_db),
) -> GlobalUpdateReportRead:
    try:
        run = get_run_by_id(db, run_id)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    return GlobalUpdateReportRead.model_validate(build_run_report(run))


@results_router.get(
    "/results",
    response_model=ModelsVersionsResultsResponse,
    dependencies=[Depends(require_admin_or_service)],
)
def read_models_versions_results(
    target_date: str | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> ModelsVersionsResultsResponse:
    from datetime import date as date_type

    parsed_date = None
    if target_date:
        try:
            parsed_date = date_type.fromisoformat(target_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date format.") from exc
    try:
        payload = get_models_versions_results(db, target_date=parsed_date)
        return ModelsVersionsResultsResponse.model_validate(payload)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc
