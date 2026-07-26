"""Request / job correlation ID via contextvars (safe across async + threads)."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_CORRELATION_ID: ContextVar[str | None] = ContextVar("correlation_id", default=None)

CORRELATION_HEADER = "X-Correlation-ID"
REQUEST_ID_HEADER = "X-Request-ID"


def get_correlation_id() -> str | None:
    return _CORRELATION_ID.get()


def set_correlation_id(value: str | None) -> None:
    _CORRELATION_ID.set(value)


def clear_correlation_id() -> None:
    _CORRELATION_ID.set(None)


def ensure_correlation_id(candidate: str | None = None) -> str:
    """Return an existing or newly generated correlation id and store it."""
    current = get_correlation_id()
    if current:
        return current
    raw = (candidate or "").strip()
    if raw:
        # Cap length; allow only safe printable characters for log/header reuse.
        cleaned = "".join(ch for ch in raw if ch.isprintable() and ch not in " \t\r\n")[:128]
        if cleaned:
            set_correlation_id(cleaned)
            return cleaned
    generated = uuid.uuid4().hex
    set_correlation_id(generated)
    return generated
