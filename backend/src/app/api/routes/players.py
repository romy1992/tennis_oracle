from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.db.session import get_db
from backend.src.app.schemas import PlayerRead
from backend.src.app.services.players import get_player, list_players


router = APIRouter(prefix="/players", tags=["players"])


@router.get("", response_model=list[PlayerRead])
def read_players(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[PlayerRead]:
    try:
        return list_players(db=db, limit=limit, offset=offset)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for players is not available.",
        ) from exc


@router.get("/{player_id}", response_model=PlayerRead)
def read_player(player_id: int, db: Session = Depends(get_db)) -> PlayerRead:
    try:
        player = get_player(db=db, player_id=player_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for players is not available.",
        ) from exc

    if player is None:
        raise HTTPException(status_code=404, detail="Player not found.")
    return player
