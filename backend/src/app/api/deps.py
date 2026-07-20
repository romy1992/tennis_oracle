"""Reusable FastAPI auth dependencies."""

from __future__ import annotations

import hmac
import logging
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.core.security import decode_access_token
from backend.src.app.db.session import get_db
from backend.src.app.services.auth import get_admin_by_username
from backend.src.entity.admin_user import AdminUser

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)
_service_header = APIKeyHeader(name="X-Service-Token", auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str = "Not authorized") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def get_current_admin(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(_bearer_scheme)
    ],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    token = credentials.credentials
    try:
        payload = decode_access_token(token, settings)
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Access token expired") from exc
    except jwt.InvalidTokenError as exc:
        logger.info("Rejected invalid admin access token")
        raise _unauthorized("Invalid access token") from exc

    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise _unauthorized("Invalid access token")

    admin = get_admin_by_username(db, username)
    if admin is None:
        raise _unauthorized("Invalid access token")
    if not admin.is_active:
        raise _forbidden("Admin account is disabled")
    return admin


def require_admin(
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> AdminUser:
    """Dependency that requires a valid active admin session."""
    return admin


def _service_token_valid(provided: str | None, expected: str | None) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def require_service_token(
    service_token: Annotated[str | None, Security(_service_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Dedicated bot/service protection via ``X-Service-Token``.

    Independent from admin JWT. Requires ``SERVICE_API_KEY`` to be configured.
    """
    expected = (settings.service_api_key or "").strip()
    if not expected:
        raise _unauthorized("Service API key is not configured")
    if not _service_token_valid(service_token, expected):
        logger.info("Rejected request with missing or invalid service token")
        raise _unauthorized("Invalid or missing service token")


def require_admin_or_service(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(_bearer_scheme)
    ],
    service_token: Annotated[str | None, Security(_service_header)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminUser | None:
    """Allow admin JWT or service token on bot-shared read endpoints.

    When ``SERVICE_API_KEY`` is empty and ``ALLOW_UNAUTHENTICATED_SERVICE_READS``
    is true, anonymous access remains allowed (local / backward compatible).
    """
    if credentials is not None and credentials.scheme.lower() == "bearer":
        return get_current_admin(credentials, db, settings)

    expected_service = (settings.service_api_key or "").strip()
    if expected_service:
        if _service_token_valid(service_token, expected_service):
            return None
        logger.info("Rejected request with missing or invalid service token")
        raise _unauthorized("Invalid or missing credentials")

    if settings.allow_unauthenticated_service_reads:
        return None

    raise _unauthorized()
