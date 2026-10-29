"""Admin authentication and bootstrap helpers."""

from __future__ import annotations

import base64
import hashlib
import logging
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings
from backend.src.app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from backend.src.entity.admin_user import AdminUser

logger = logging.getLogger(__name__)


def _password_fernet(settings: Settings) -> Fernet:
    secret = (settings.admin_jwt_secret or "").strip()
    if not secret:
        raise RuntimeError("ADMIN_JWT_SECRET mancante: impossibile cifrare la password")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest()))


def encrypt_password(password: str, settings: Settings) -> str:
    return _password_fernet(settings).encrypt(password.encode("utf-8")).decode("utf-8")


def reveal_admin_password(admin: AdminUser, settings: Settings) -> str | None:
    """Password in chiaro per l'occhio; None se non salvata o non decifrabile
    (per esempio dopo la rotazione di ADMIN_JWT_SECRET: va reimpostata)."""
    if not admin.password_enc:
        return None
    try:
        return _password_fernet(settings).decrypt(admin.password_enc.encode("utf-8")).decode("utf-8")
    except (InvalidToken, RuntimeError):
        return None


def get_admin_by_username(db: Session, username: str) -> AdminUser | None:
    return (
        db.query(AdminUser)
        .filter(AdminUser.username == username)
        .one_or_none()
    )


def authenticate_admin(
    db: Session,
    *,
    username: str,
    password: str,
) -> AdminUser | None:
    admin = get_admin_by_username(db, username)
    if admin is None:
        return None
    if not admin.is_active:
        return None
    if not verify_password(password, admin.password_hash):
        return None
    return admin


def issue_access_token(admin: AdminUser, settings: Settings) -> tuple[str, datetime]:
    return create_access_token(
        subject=admin.username,
        settings=settings,
        extra_claims={"admin_id": admin.id},
    )


def ensure_bootstrap_admin(db: Session, settings: Settings) -> AdminUser | None:
    """Create the first admin from env credentials when the table is empty.

    Does not log passwords. If an admin already exists, returns None without changes.
    """
    username = (settings.admin_username or "").strip()
    password = settings.admin_password or ""
    if not username or not password:
        return None

    existing_count = db.query(AdminUser).count()
    if existing_count > 0:
        # Admin gia' nel DB: l'ambiente non comanda piu'. Unico uso residuo:
        # salvare la copia cifrata per l'occhio, se la password dell'ambiente
        # coincide con quella nel DB.
        admin = get_admin_by_username(db, username)
        if (
            admin is not None
            and not admin.password_enc
            and (settings.admin_jwt_secret or "").strip()
            and verify_password(password, admin.password_hash)
        ):
            admin.password_enc = encrypt_password(password, settings)
            db.commit()
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    admin = AdminUser(
        username=username,
        password_hash=hash_password(password),
        password_enc=(
            encrypt_password(password, settings)
            if (settings.admin_jwt_secret or "").strip()
            else None
        ),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    logger.info("Bootstrapped initial admin user username=%s", admin.username)
    return admin


class CurrentPasswordError(Exception):
    """The supplied current password does not match."""


class UsernameTakenError(Exception):
    """Another admin already uses the requested username."""


def change_admin_credentials(
    db: Session,
    admin: AdminUser,
    *,
    current_password: str,
    new_username: str | None = None,
    new_password: str | None = None,
    settings: Settings | None = None,
) -> AdminUser:
    """Update username and/or password after re-checking the current password.

    Never logs password material.
    """
    if not verify_password(current_password, admin.password_hash):
        raise CurrentPasswordError()
    if new_username is not None and new_username != admin.username:
        if get_admin_by_username(db, new_username) is not None:
            raise UsernameTakenError()
        admin.username = new_username
    if new_password is not None:
        admin.password_hash = hash_password(new_password)
        if settings is not None:
            admin.password_enc = encrypt_password(new_password, settings)
    admin.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(admin)
    logger.info("Admin credentials updated admin_id=%s", admin.id)
    return admin
