"""Frozen comparison of the current coupons against a short match-winner shape."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.schemas.slip_shape_trial import SlipShapeTrialRead
from backend.src.app.services.slip_shape_trial import build_slip_shape_trial


router = APIRouter(
    prefix="/slip-shape-trial",
    tags=["slip-shape-trial"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=SlipShapeTrialRead)
def read_slip_shape_trial(db: Session = Depends(get_db)) -> SlipShapeTrialRead:
    try:
        return SlipShapeTrialRead.model_validate(build_slip_shape_trial(db))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Impossibile leggere le schedine del periodo di prova.",
        ) from exc
