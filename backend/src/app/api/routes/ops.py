"""Admin operational monitoring endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.core.config import Settings, get_settings
from backend.src.app.db.session import get_db
from backend.src.app.observability.notify import run_and_alert_ops_checks
from backend.src.app.observability.ops_checks import run_ops_checks

router = APIRouter(
    prefix="/ops",
    tags=["ops"],
    dependencies=[Depends(require_admin)],
)


@router.get("/checks")
def get_ops_checks(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    alert: bool = False,
) -> dict:
    """Run import / predictions / duration checks. Optional ``alert=true`` notifies admins."""
    if alert:
        return run_and_alert_ops_checks(db, settings)
    return run_ops_checks(
        db,
        import_max_age_hours=settings.ops_import_max_age_hours,
        predictions_lookback_hours=settings.ops_predictions_lookback_hours,
        max_duration_seconds=settings.ops_pipeline_max_duration_seconds,
        public_model_version=settings.public_model_version,
        public_model_name=settings.public_model_name,
    )
