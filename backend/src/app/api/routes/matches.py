from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.app.db.session import get_db
from src.app.schemas import MatchRead
from src.app.services.matches import get_match, list_matches


router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("", response_model=list[MatchRead])
def read_matches(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[MatchRead]:
    try:
        return list_matches(db=db, limit=limit, offset=offset)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for matches is not available.",
        ) from exc


@router.get("/{match_id}", response_model=MatchRead)
def read_match(match_id: int, db: Session = Depends(get_db)) -> MatchRead:
    try:
        match = get_match(db=db, match_id=match_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for matches is not available.",
        ) from exc

    if match is None:
        raise HTTPException(status_code=404, detail="Match not found.")
    return match
