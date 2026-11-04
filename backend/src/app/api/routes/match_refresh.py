from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.services.single_event_refresh import SingleEventRefreshBusy, refresh_single_event

router = APIRouter(
    prefix="/matches",
    tags=["match-refresh"],
    dependencies=[Depends(require_admin)],
)


@router.post("/{event_key}/refresh")
def refresh_one_match(event_key: int, db: Session = Depends(get_db)) -> dict:
    """Aggiorna UNA partita: risultato e predizioni dei mercati (vedi `single_event_refresh`)."""
    try:
        result = refresh_single_event(db, event_key)
    except SingleEventRefreshBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available for refresh.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=f"Partita non trovata: {event_key}")
    return result
