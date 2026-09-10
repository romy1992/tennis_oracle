"""Admin-only runtime settings for external providers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.core.config import Settings, get_settings
from backend.src.app.core.security import verify_password
from backend.src.app.db.session import get_db
from backend.src.app.schemas.settings import (
    ApiTennisConnectionTestRequest,
    ApiTennisConnectionTestResponse,
    ApiTennisKeyUpdateRequest,
    ApiTennisKeyUpdateResponse,
    ApiTennisProviderSettingsRead,
)
from backend.src.app.services.runtime_secrets import (
    API_TENNIS_SECRET_KEY,
    RuntimeSecretError,
    api_tennis_secret_status,
    runtime_secret_storage_ready,
    set_runtime_secret,
)
from backend.src.app.services.subscription_dashboard import log_admin_action
from backend.src.entity.admin_user import AdminUser
from backend.src.utility.request_api import ApiTennisError, request_api

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(require_admin)],
)


def _provider_settings(
    db: Session, settings: Settings
) -> ApiTennisProviderSettingsRead:
    secret_status = api_tennis_secret_status(db, settings=settings)
    return ApiTennisProviderSettingsRead(
        environment=settings.app_env,
        base_url=(settings.api_tennis_base or "").strip() or None,
        timeout_seconds=settings.api_tennis_timeout,
        **secret_status,
    )


def _clean_api_key(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) < 8 or len(cleaned) > 512:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La chiave deve contenere tra 8 e 512 caratteri.",
        )
    return cleaned


def _verify_provider_key(api_key: str) -> None:
    try:
        request_api(method="get_events", api_key_override=api_key)
    except ApiTennisError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Chiave non salvata: verifica API-Tennis fallita. {exc}",
        ) from exc


@router.get(
    "/providers/api-tennis",
    response_model=ApiTennisProviderSettingsRead,
)
def read_api_tennis_settings(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApiTennisProviderSettingsRead:
    try:
        return _provider_settings(db, settings)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503, detail="Database non disponibile."
        ) from exc


@router.post(
    "/providers/api-tennis/test",
    response_model=ApiTennisConnectionTestResponse,
)
def test_api_tennis_connection(
    payload: ApiTennisConnectionTestRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApiTennisConnectionTestResponse:
    candidate = None
    if payload.api_key is not None:
        candidate = _clean_api_key(payload.api_key.get_secret_value())

    try:
        if candidate is None:
            provider_status = _provider_settings(db, settings)
            if not provider_status.usable:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Nessuna chiave API-Tennis utilizzabile è configurata.",
                )
            request_api(method="get_events")
        else:
            _verify_provider_key(candidate)
    except HTTPException:
        raise
    except ApiTennisError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Connessione API-Tennis fallita. {exc}",
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503, detail="Database non disponibile."
        ) from exc

    return ApiTennisConnectionTestResponse(
        ok=True,
        message="Connessione API-Tennis verificata correttamente.",
    )


@router.patch(
    "/providers/api-tennis/key",
    response_model=ApiTennisKeyUpdateResponse,
)
def update_api_tennis_key(
    payload: ApiTennisKeyUpdateRequest,
    admin: Annotated[AdminUser, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApiTennisKeyUpdateResponse:
    if not verify_password(
        payload.admin_password.get_secret_value(), admin.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password amministratore non valida.",
        )

    api_key = _clean_api_key(payload.api_key.get_secret_value())
    if not runtime_secret_storage_ready(settings):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "RUNTIME_SECRETS_MASTER_KEY non configurata correttamente "
                "per questo ambiente."
            ),
        )
    verified = False
    if payload.verify_before_save:
        _verify_provider_key(api_key)
        verified = True

    try:
        row = set_runtime_secret(
            db,
            settings=settings,
            key=API_TENNIS_SECRET_KEY,
            value=api_key,
            updated_by=admin.username,
        )
        log_admin_action(
            db,
            admin=admin,
            action="provider_secret_update",
            target_type="runtime_secret",
            target_id=API_TENNIS_SECRET_KEY,
            description="Chiave API-Tennis aggiornata dalle impostazioni.",
            context={
                "provider": "api-tennis",
                "environment": settings.app_env,
                "fingerprint": row.fingerprint,
                "verified_before_save": verified,
            },
            commit=False,
        )
        db.commit()
        db.refresh(row)
        current = _provider_settings(db, settings)
    except RuntimeSecretError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="Database non disponibile."
        ) from exc

    return ApiTennisKeyUpdateResponse(
        message="Nuova chiave API-Tennis salvata e attivata.",
        verified=verified,
        settings=current,
    )
