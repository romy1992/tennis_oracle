"""Shared helpers for long-running background jobs (walk-forward, calibration)."""

from __future__ import annotations

import threading
import time
from typing import Callable

from sqlalchemy.orm import Session


class BackgroundJobCancelled(Exception):
    """Raised when a cooperative cancellation is detected."""


_active_thread_lock = threading.Lock()
_cancel_requested: set[int] = set()
_cancel_cache: dict[int, tuple[float, bool]] = {}


def get_active_thread_lock() -> threading.Lock:
    return _active_thread_lock


def mark_cancel_requested(run_id: int) -> None:
    _cancel_requested.add(run_id)
    _cancel_cache[run_id] = (time.monotonic(), True)


def clear_cancel_state(run_id: int) -> None:
    _cancel_requested.discard(run_id)
    _cancel_cache.pop(run_id, None)


def is_cancel_requested(run_id: int, *, db_check: Callable[[], bool] | None = None) -> bool:
    if run_id in _cancel_requested:
        return True
    now = time.monotonic()
    cached = _cancel_cache.get(run_id)
    if cached and now - cached[0] < 1.0:
        return cached[1]
    value = db_check() if db_check is not None else False
    _cancel_cache[run_id] = (now, value)
    if value:
        _cancel_requested.add(run_id)
    return value


def check_cancelled(run_id: int, *, db_check: Callable[[], bool] | None = None) -> None:
    if is_cancel_requested(run_id, db_check=db_check):
        raise BackgroundJobCancelled(f"Run {run_id} cancelled.")


def update_run_progress(
    db: Session,
    run: object,
    *,
    phase: str | None = None,
    progress_pct: float | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
) -> None:
    if phase is not None:
        run.current_phase = phase  # type: ignore[attr-defined]
    if progress_pct is not None:
        run.progress_pct = max(0.0, min(100.0, progress_pct))  # type: ignore[attr-defined]
    if progress_current is not None:
        run.progress_current = progress_current  # type: ignore[attr-defined]
    if progress_total is not None:
        run.progress_total = progress_total  # type: ignore[attr-defined]
    db.commit()
