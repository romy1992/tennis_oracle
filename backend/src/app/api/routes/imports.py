from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.ml.model_versioning import ModelVersion
from backend.src.app.schemas.imports import (
    ImportFixturesRequest,
    ImportFixturesResponse,
    ImportStatusResponse,
    RefreshMatchesResponse,
)
from backend.src.app.services.import_state import get_import_status
from backend.src.app.services.imports import import_played_fixtures, refresh_matches


router = APIRouter(
    prefix="/imports",
    tags=["imports"],
    dependencies=[Depends(require_admin)],
)


@router.get("/status", response_model=ImportStatusResponse)
def read_import_status(db: Session = Depends(get_db)) -> ImportStatusResponse:
    try:
        return ImportStatusResponse.model_validate(get_import_status(db))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database not available for import status.",
        ) from exc


@router.post("/refresh", response_model=RefreshMatchesResponse)
def refresh_upcoming_matches(
    model_version: ModelVersion = "v2",
    model_name: str | None = None,
    days_forward: int = 10,
    force_next_import: bool = False,
    db: Session = Depends(get_db),
) -> RefreshMatchesResponse:
    try:
        result = refresh_matches(
            db,
            days_forward=days_forward,
            model_version=model_version,
            model_name=model_name,
            force_next_import=force_next_import,
        )
        return RefreshMatchesResponse.model_validate(result)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database not available for refresh.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/fixtures", response_model=ImportFixturesResponse)
def import_completed_fixtures(
    body: ImportFixturesRequest,
    db: Session = Depends(get_db),
) -> ImportFixturesResponse:
    try:
        result = import_played_fixtures(db, days_back=body.days_back)
        return ImportFixturesResponse.model_validate(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database not available for fixture import.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
