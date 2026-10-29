"""Admin authentication endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.core.config import Settings, get_settings
from backend.src.app.db.session import get_db
from backend.src.app.schemas.auth import (
    AdminSessionResponse,
    ChangeCredentialsRequest,
    LoginRequest,
    LogoutResponse,
    TokenResponse,
)
from backend.src.app.services.auth import (
    CurrentPasswordError,
    UsernameTakenError,
    authenticate_admin,
    change_admin_credentials,
    issue_access_token,
)
from backend.src.entity.admin_user import AdminUser
from backend.src.utility.sensitive_data import sanitize_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if not (settings.admin_jwt_secret or "").strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured (ADMIN_JWT_SECRET).",
        )

    admin = authenticate_admin(db, username=body.username, password=body.password)
    if admin is None:
        # Never log password or token material.
        logger.info(
            "Failed admin login attempt payload=%s",
            sanitize_payload({"username": body.username}),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_at = issue_access_token(admin, settings)
    logger.info("Admin login succeeded username=%s", admin.username)
    return TokenResponse(access_token=token, expires_at=expires_at)


@router.get("/me", response_model=AdminSessionResponse)
def read_session(
    admin: AdminUser = Depends(require_admin),
) -> AdminSessionResponse:
    return AdminSessionResponse(
        id=admin.id,
        username=admin.username,
        is_active=admin.is_active,
        authenticated=True,
    )


@router.post("/logout", response_model=LogoutResponse)
def logout(
    _admin: AdminUser = Depends(require_admin),
) -> LogoutResponse:
    """Stateless JWT logout: client must discard the token."""
    return LogoutResponse(ok=True, message="Logged out")


@router.put("/credentials", response_model=TokenResponse)
def update_credentials(
    body: ChangeCredentialsRequest,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Change username and/or password. Returns a fresh token because the JWT
    subject is the username. Wrong current password is 403 (not 401) so the
    client does not treat it as an expired session."""
    try:
        admin = change_admin_credentials(
            db,
            admin,
            current_password=body.current_password,
            new_username=body.new_username,
            new_password=body.new_password,
        )
    except CurrentPasswordError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect",
        )
    except UsernameTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already in use",
        )
    token, expires_at = issue_access_token(admin, settings)
    return TokenResponse(access_token=token, expires_at=expires_at)
