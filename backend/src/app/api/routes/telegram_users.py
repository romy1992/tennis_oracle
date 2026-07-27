"""Admin API for Telegram beta user whitelist management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.schemas.telegram_users import (
    TelegramUserInviteCreate,
    TelegramUserListResponse,
    TelegramUserRead,
)
from backend.src.app.services.telegram_users import (
    TelegramUserError,
    activate_telegram_user,
    block_telegram_user,
    get_telegram_user,
    invite_telegram_user,
    list_telegram_users,
    suspend_telegram_user,
)


router = APIRouter(
    prefix="/telegram/users",
    tags=["telegram-users"],
    dependencies=[Depends(require_admin)],
)


def _raise_domain(exc: TelegramUserError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("", response_model=TelegramUserListResponse)
def search_telegram_users(
    q: str | None = Query(default=None, description="Search id, username, name, invite"),
    status: str | None = Query(default=None),
    user_id: int | None = Query(default=None, alias="telegram_user_id"),
    username: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> TelegramUserListResponse:
    try:
        return list_telegram_users(
            db,
            q=q,
            status=status,
            telegram_user_id=user_id,
            username=username,
            limit=limit,
            offset=offset,
        )
    except TelegramUserError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram users is not available.",
        ) from exc


@router.get("/{telegram_user_id}", response_model=TelegramUserRead)
def read_telegram_user(
    telegram_user_id: int,
    db: Session = Depends(get_db),
) -> TelegramUserRead:
    try:
        row = get_telegram_user(db, telegram_user_id)
        if row is None:
            raise TelegramUserError("Utente Telegram non trovato.", status_code=404)
        return TelegramUserRead.model_validate(row)
    except TelegramUserError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram users is not available.",
        ) from exc


@router.post("", response_model=TelegramUserRead, status_code=201)
def create_telegram_user_invite(
    payload: TelegramUserInviteCreate,
    db: Session = Depends(get_db),
) -> TelegramUserRead:
    try:
        return invite_telegram_user(db, payload)
    except TelegramUserError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram users is not available.",
        ) from exc


@router.post("/{telegram_user_id}/activate", response_model=TelegramUserRead)
def activate_user(
    telegram_user_id: int,
    db: Session = Depends(get_db),
) -> TelegramUserRead:
    try:
        return activate_telegram_user(db, telegram_user_id)
    except TelegramUserError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram users is not available.",
        ) from exc


@router.post("/{telegram_user_id}/suspend", response_model=TelegramUserRead)
def suspend_user(
    telegram_user_id: int,
    db: Session = Depends(get_db),
) -> TelegramUserRead:
    try:
        return suspend_telegram_user(db, telegram_user_id)
    except TelegramUserError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram users is not available.",
        ) from exc


@router.post("/{telegram_user_id}/block", response_model=TelegramUserRead)
def block_user(
    telegram_user_id: int,
    db: Session = Depends(get_db),
) -> TelegramUserRead:
    try:
        return block_telegram_user(db, telegram_user_id)
    except TelegramUserError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database table for telegram users is not available.",
        ) from exc
