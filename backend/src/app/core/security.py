"""Password hashing and JWT access-token helpers for admin auth."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from backend.src.app.core.config import Settings


ALGORITHM = "HS256"
TOKEN_TYPE_ACCESS = "access"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    *,
    subject: str,
    settings: Settings,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.admin_jwt_expire_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": TOKEN_TYPE_ACCESS,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.admin_jwt_secret, algorithm=ALGORITHM)
    return token, expire


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    payload = jwt.decode(token, settings.admin_jwt_secret, algorithms=[ALGORITHM])
    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise jwt.InvalidTokenError("Invalid token type")
    return payload
