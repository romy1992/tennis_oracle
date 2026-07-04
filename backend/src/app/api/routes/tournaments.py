from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.db.session import get_db
from backend.src.app.schemas import TournamentRead
from backend.src.app.services.tournaments import list_tournaments


router = APIRouter(prefix="/tournaments", tags=["tournaments"])


@router.get("", response_model=list[TournamentRead])
def read_tournaments(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[TournamentRead]:
    try:
        return list_tournaments(db=db, limit=limit, offset=offset)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for tournaments is not available.",
        ) from exc
