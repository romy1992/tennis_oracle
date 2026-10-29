"""Admin authentication and bootstrap helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings
from backend.src.app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from backend.src.entity.admin_user import AdminUser

logger = logging.getLogger(__name__)


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
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    admin = AdminUser(
        username=username,
        password_hash=hash_password(password),
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
    admin.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(admin)
    logger.info("Admin credentials updated admin_id=%s", admin.id)
    return admin
