"""Small in-process resilience primitives for outbound provider calls.

- ``backoff_delay``: exponential backoff with jitter, capped.
- ``CircuitBreaker``: closed / open / half-open, thread-safe, injectable clock.

No external dependency and no shared state across processes: every worker
keeps its own breaker, which is enough to stop hammering a provider that is
down and to fail fast instead of waiting for N timeouts in a row.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Callable

STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half_open"


def backoff_delay(
    attempt: int,
    *,
    base_seconds: float,
    max_seconds: float,
    rng: Callable[[], float] = random.random,
) -> float:
    """Delay before retry number ``attempt`` (1-based), "equal jitter" variant.

    Half of the exponential step is fixed and half is random, so retries from
    concurrent workers do not align while the wait never collapses to zero.
    """
    if attempt < 1 or base_seconds <= 0:
        return 0.0
    step = min(max_seconds, base_seconds * (2 ** (attempt - 1)))
    return step / 2.0 + rng() * step / 2.0


class CircuitBreaker:
    """Consecutive-failure circuit breaker.

    closed    -> calls flow; ``failure_threshold`` consecutive failures open it.
    open      -> calls are rejected until ``recovery_seconds`` have elapsed.
    half_open -> a single probe call is admitted: success closes the breaker,
                 failure re-opens it for another ``recovery_seconds``.

    ``failure_threshold <= 0`` disables the breaker (always closed).
    """

    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = int(failure_threshold)
        self.recovery_seconds = float(recovery_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._state = STATE_CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def enabled(self) -> bool:
        return self.failure_threshold > 0

    @property
    def state(self) -> str:
        with self._lock:
            return self._current_state_locked()

    def _current_state_locked(self) -> str:
        if (
            self._state == STATE_OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self.recovery_seconds
        ):
            self._state = STATE_HALF_OPEN
            self._probe_in_flight = False
        return self._state

    def seconds_until_retry(self) -> float:
        with self._lock:
            if self._current_state_locked() != STATE_OPEN or self._opened_at is None:
                return 0.0
            return max(0.0, self.recovery_seconds - (self._clock() - self._opened_at))

    def allow_request(self) -> bool:
        if not self.enabled:
            return True
        with self._lock:
            state = self._current_state_locked()
            if state == STATE_CLOSED:
                return True
            if state == STATE_HALF_OPEN and not self._probe_in_flight:
                self._probe_in_flight = True
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._state = STATE_CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    def record_failure(self) -> bool:
        """Register a failed call. Returns True when this failure opened the breaker."""
        if not self.enabled:
            return False
        with self._lock:
            state = self._current_state_locked()
            self._consecutive_failures += 1
            if state == STATE_HALF_OPEN or self._consecutive_failures >= self.failure_threshold:
                opened_now = self._state != STATE_OPEN
                self._state = STATE_OPEN
                self._opened_at = self._clock()
                self._probe_in_flight = False
                return opened_now
            return False

    def release_probe(self) -> None:
        """Give back the half-open slot when the probe ended without a verdict."""
        with self._lock:
            self._probe_in_flight = False

    def reset(self) -> None:
        self.record_success()
