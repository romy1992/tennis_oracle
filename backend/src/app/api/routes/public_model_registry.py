"""Admin API for the official public model registry (ML-07)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin, require_admin_or_service
from backend.src.app.db.session import get_db
from backend.src.app.schemas.public_model_registry import (
    PublicModelRegistryActionResponse,
    PublicModelRegistryActivateRequest,
    PublicModelRegistryActiveRead,
    PublicModelRegistryCandidateCreate,
    PublicModelRegistryEntryRead,
    PublicModelRegistryListResponse,
    PublicModelRegistryRollbackRequest,
    PublicModelRegistryStatus,
)
from backend.src.app.services.public_model_registry import (
    activate_registry_entry,
    entry_to_read,
    get_active_registry_entry,
    list_registry_entries,
    register_candidate,
    rollback_active_registry_entry,
)
from backend.src.entity.admin_user import AdminUser

router = APIRouter(
    prefix="/public-model-registry",
    tags=["public-model-registry"],
)


@router.get("/active", response_model=PublicModelRegistryActiveRead)
def read_active_public_model(
    db: Session = Depends(get_db),
    _auth: AdminUser | None = Depends(require_admin_or_service),
) -> PublicModelRegistryActiveRead:
    """Return the single active public model (bot + live publication)."""
    active = get_active_registry_entry(db)
    if active is None:
        raise HTTPException(status_code=404, detail="Nessun modello pubblico attivo nel registro")
    return PublicModelRegistryActiveRead(
        model_version=active.model_version,
        model_name=active.model_name,
        registry_entry_id=active.id,
        activated_at=active.activated_at,
    )


@router.get("", response_model=PublicModelRegistryListResponse)
def list_entries(
    status: PublicModelRegistryStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
) -> PublicModelRegistryListResponse:
    rows, total = list_registry_entries(db, status=status, limit=limit, offset=offset)
    active = get_active_registry_entry(db)
    return PublicModelRegistryListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[entry_to_read(row) for row in rows],
        active=entry_to_read(active) if active is not None else None,
    )


@router.post("/candidates", response_model=PublicModelRegistryEntryRead, status_code=201)
def create_candidate(
    body: PublicModelRegistryCandidateCreate,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
) -> PublicModelRegistryEntryRead:
    try:
        row = register_candidate(
            db,
            model_version=body.model_version.strip(),
            model_name=body.model_name.strip(),
            motivation=body.motivation,
            approval_metrics=body.approval_metrics,
            walk_forward_run_id=body.walk_forward_run_id,
            calibration_run_id=body.calibration_run_id,
            created_by="admin_api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return entry_to_read(row)


@router.post("/entries/{entry_id}/activate", response_model=PublicModelRegistryActionResponse)
def activate_entry(
    entry_id: int,
    body: PublicModelRegistryActivateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
) -> PublicModelRegistryActionResponse:
    try:
        entry, previous = activate_registry_entry(
            db,
            entry_id,
            motivation=body.motivation.strip(),
            created_by="admin_api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PublicModelRegistryActionResponse(
        entry=entry_to_read(entry),
        previous_active=entry_to_read(previous) if previous is not None else None,
        message=f"Modello pubblico attivo: {entry.model_version}/{entry.model_name}",
    )


@router.post("/rollback", response_model=PublicModelRegistryActionResponse)
def rollback_active(
    body: PublicModelRegistryRollbackRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_admin),
) -> PublicModelRegistryActionResponse:
    try:
        restored, retired = rollback_active_registry_entry(
            db,
            motivation=body.motivation.strip(),
            created_by="admin_api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PublicModelRegistryActionResponse(
        entry=entry_to_read(restored),
        previous_active=entry_to_read(retired),
        message=(
            f"Rollback completato: attivo {restored.model_version}/{restored.model_name} "
            f"(ex id={retired.id})"
        ),
    )
