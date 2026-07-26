"""Database-backed distributed lock for the global-update pipeline."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.entity.pipeline_lock import PipelineLock

logger = logging.getLogger(__name__)

GLOBAL_UPDATE_LOCK_NAME = "global_update"
DEFAULT_LOCK_TTL_SECONDS = 6 * 60 * 60


def new_owner_token() -> str:
    return uuid.uuid4().hex


def ensure_lock_row(db: Session, name: str = GLOBAL_UPDATE_LOCK_NAME) -> PipelineLock:
    lock = db.get(PipelineLock, name)
    if lock is not None:
        return lock
    lock = PipelineLock(name=name)
    db.add(lock)
    db.commit()
    return lock


def _load_for_update(db: Session, name: str) -> PipelineLock:
    ensure_lock_row(db, name)
    stmt = select(PipelineLock).where(PipelineLock.name == name).with_for_update()
    lock = db.scalars(stmt).one()
    return lock


def acquire_pipeline_lock(
    db: Session,
    *,
    name: str = GLOBAL_UPDATE_LOCK_NAME,
    owner_token: str,
    run_id: int | None = None,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> bool:
    """Try to acquire a named lease. Returns True on success."""
    now = datetime.now()
    lock = _load_for_update(db, name)
    held = (
        lock.owner_token is not None
        and lock.expires_at is not None
        and lock.expires_at > now
    )
    if held and lock.owner_token != owner_token:
        db.rollback()
        logger.info(
            "Pipeline lock busy name=%s holder_run_id=%s expires_at=%s",
            name,
            lock.run_id,
            lock.expires_at,
        )
        return False

    lock.owner_token = owner_token
    lock.run_id = run_id
    lock.acquired_at = now
    lock.expires_at = now + timedelta(seconds=max(ttl_seconds, 60))
    lock.heartbeat_at = now
    db.commit()
    return True


def heartbeat_pipeline_lock(
    db: Session,
    *,
    name: str = GLOBAL_UPDATE_LOCK_NAME,
    owner_token: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> bool:
    """Extend the lease if still owned by ``owner_token``."""
    now = datetime.now()
    lock = _load_for_update(db, name)
    if lock.owner_token != owner_token:
        db.rollback()
        return False
    lock.heartbeat_at = now
    lock.expires_at = now + timedelta(seconds=max(ttl_seconds, 60))
    db.commit()
    return True


def release_pipeline_lock(
    db: Session,
    *,
    name: str = GLOBAL_UPDATE_LOCK_NAME,
    owner_token: str,
) -> bool:
    """Release the lease if owned by ``owner_token``."""
    lock = _load_for_update(db, name)
    if lock.owner_token != owner_token:
        db.rollback()
        return False
    lock.owner_token = None
    lock.run_id = None
    lock.acquired_at = None
    lock.expires_at = None
    lock.heartbeat_at = None
    db.commit()
    return True


def get_pipeline_lock(
    db: Session,
    *,
    name: str = GLOBAL_UPDATE_LOCK_NAME,
) -> PipelineLock | None:
    return db.get(PipelineLock, name)
