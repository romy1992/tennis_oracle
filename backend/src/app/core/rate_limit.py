"""PostgreSQL-backed fixed-window rate limiting (multi-instance safe).

Counters live in ``rate_limit_bucket`` so API replicas and the Telegram bot
share the same quotas. Uses row locks / upsert semantics compatible with
PostgreSQL and SQLite (tests).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.src.entity.rate_limit_bucket import RateLimitBucket

logger = logging.getLogger(__name__)

# Overridable in tests so middleware/bot use the same in-memory SQLite session.
_session_factory: sessionmaker | Callable[[], Session] | None = None


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    hit_count: int
    bucket_key: str


def set_rate_limit_session_factory(
    factory: sessionmaker | Callable[[], Session] | None,
) -> None:
    """Override DB session factory (tests). Pass ``None`` to restore default."""
    global _session_factory
    _session_factory = factory


def get_rate_limit_session() -> Session:
    """Return a new SQLAlchemy session for rate-limit checks."""
    if _session_factory is not None:
        return _session_factory()
    from backend.src.app.db.session import SessionLocal

    return SessionLocal()


def window_start_utc(now: datetime, window_seconds: int) -> datetime:
    """Align ``now`` to the start of the current fixed window (UTC, naive)."""
    if window_seconds <= 0:
        window_seconds = 60
    if now.tzinfo is not None:
        now_utc = now.astimezone(timezone.utc)
    else:
        # Naive datetimes are treated as UTC (do not use .timestamp() on naive).
        now_utc = now.replace(tzinfo=timezone.utc)
    epoch = int(now_utc.timestamp())
    aligned = epoch - (epoch % window_seconds)
    return datetime.fromtimestamp(aligned, tz=timezone.utc).replace(tzinfo=None)


def fingerprint_secret(value: str) -> str:
    """Stable non-reversible fingerprint for tokens (never log the raw value)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def consume_rate_limit(
    session: Session,
    *,
    bucket_key: str,
    limit: int,
    window_seconds: int,
    now: datetime | None = None,
) -> RateLimitDecision:
    """Increment the counter for ``bucket_key`` and return allow/deny decision.

    Concurrent callers across processes are serialized with ``FOR UPDATE``
    when the dialect supports it; IntegrityError races fall back to a retry.
    """
    if limit <= 0:
        # Disabled limit for this tier: always allow without writing.
        return RateLimitDecision(
            allowed=True,
            limit=limit,
            remaining=0,
            retry_after=0,
            hit_count=0,
            bucket_key=bucket_key,
        )

    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    ws = window_start_utc(now, window_seconds)
    key = bucket_key[:255]

    hit_count = _increment_bucket(session, key=key, window_start=ws, now=now)
    allowed = hit_count <= limit
    remaining = max(0, limit - hit_count)
    window_end = ws + timedelta(seconds=window_seconds)
    retry_after = max(1, int((window_end - now).total_seconds()) + 1) if not allowed else 0

    if not allowed:
        # No secrets in key (IP / fingerprints / telegram ids only).
        logger.warning(
            "Rate limit exceeded bucket_key=%s hit_count=%s limit=%s retry_after=%s",
            key,
            hit_count,
            limit,
            retry_after,
        )

    return RateLimitDecision(
        allowed=allowed,
        limit=limit,
        remaining=remaining,
        retry_after=retry_after,
        hit_count=hit_count,
        bucket_key=key,
    )


def _increment_bucket(
    session: Session,
    *,
    key: str,
    window_start: datetime,
    now: datetime,
) -> int:
    for _ in range(3):
        try:
            row = (
                session.query(RateLimitBucket)
                .filter(RateLimitBucket.bucket_key == key)
                .with_for_update()
                .one_or_none()
            )
            if row is None:
                row = RateLimitBucket(
                    bucket_key=key,
                    window_start=window_start,
                    hit_count=1,
                    updated_at=now,
                )
                session.add(row)
                session.commit()
                return 1

            if row.window_start < window_start:
                row.window_start = window_start
                row.hit_count = 1
            else:
                row.hit_count = int(row.hit_count) + 1
            row.updated_at = now
            session.commit()
            return int(row.hit_count)
        except IntegrityError:
            session.rollback()
            continue

    # Last resort without lock (should be rare).
    session.rollback()
    row = (
        session.query(RateLimitBucket)
        .filter(RateLimitBucket.bucket_key == key)
        .one_or_none()
    )
    if row is None:
        row = RateLimitBucket(
            bucket_key=key,
            window_start=window_start,
            hit_count=1,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        return 1
    if row.window_start < window_start:
        row.window_start = window_start
        row.hit_count = 1
    else:
        row.hit_count = int(row.hit_count) + 1
    row.updated_at = now
    session.commit()
    return int(row.hit_count)


def purge_stale_buckets(
    session: Session,
    *,
    older_than: datetime,
) -> int:
    """Delete counters whose window is older than ``older_than``. Returns rows deleted."""
    deleted = (
        session.query(RateLimitBucket)
        .filter(RateLimitBucket.window_start < older_than)
        .delete(synchronize_session=False)
    )
    session.commit()
    return int(deleted or 0)
