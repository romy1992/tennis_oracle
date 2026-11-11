"""HTTP client for the external tennis API (API-Tennis)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests
from requests import exceptions as requests_exc

from backend.src.app.core.env_files import load_backend_env_files
from backend.src.app.services.runtime_secrets import (
    RuntimeSecretError,
    resolve_api_tennis_key,
)
from backend.src.utility.resilience import (
    STATE_CLOSED,
    CircuitBreaker,
    backoff_delay,
)
from backend.src.utility.sensitive_data import (
    sanitize_payload,
    sanitize_text,
    sanitize_url,
)

logger = logging.getLogger(__name__)

load_backend_env_files(override=False)
API_KEY = os.getenv("API_TENNIS_KEY")
BASE_URL = os.getenv("API_TENNIS_BASE")

# Explicit HTTP timeout (seconds). Override with API_TENNIS_TIMEOUT.
DEFAULT_TIMEOUT_SECONDS = 30.0

# Transient failures (timeout, connection error, HTTP 429/5xx) are retried with
# exponential backoff + jitter. Provider-declared errors and invalid payloads
# are never retried: the provider answered, repeating the call cannot help.
#   API_TENNIS_MAX_RETRIES                 extra attempts after the first one (0 disables)
#   API_TENNIS_RETRY_BACKOFF_SECONDS       first backoff step
#   API_TENNIS_RETRY_BACKOFF_MAX_SECONDS   cap for a single wait (also caps Retry-After)
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.5
DEFAULT_RETRY_BACKOFF_MAX_SECONDS = 8.0

# Circuit breaker: after N consecutive failed attempts the client fails fast
# (ApiTennisCircuitOpenError) for the recovery window, then lets one probe through.
#   API_TENNIS_CIRCUIT_FAILURE_THRESHOLD   consecutive failed attempts (0 disables)
#   API_TENNIS_CIRCUIT_RECOVERY_SECONDS    how long the breaker stays open
DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 5
DEFAULT_CIRCUIT_RECOVERY_SECONDS = 60.0

METRIC_REQUESTS = "api_tennis_requests_total"
METRIC_RETRIES = "api_tennis_retries_total"
METRIC_DURATION = "api_tennis_request_duration_seconds"
METRIC_BREAKER_TRANSITIONS = "api_tennis_circuit_breaker_transitions_total"

# Indirection so tests (and callers with their own scheduler) never really wait.
_sleep = time.sleep


class ApiTennisError(RuntimeError):
    """Base error for API-Tennis client failures (safe for logging)."""


class ApiTennisTimeoutError(ApiTennisError):
    """Request exceeded the configured timeout."""


class ApiTennisNetworkError(ApiTennisError):
    """Network / connection failure talking to API-Tennis."""


class ApiTennisCircuitOpenError(ApiTennisNetworkError):
    """Call rejected without contacting API-Tennis: the circuit breaker is open."""

    def __init__(self, message: str, *, retry_after_seconds: float = 0.0):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ApiTennisHttpError(ApiTennisError):
    """Non-success HTTP status from API-Tennis."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ApiTennisInvalidResponseError(ApiTennisError):
    """Response body is not valid JSON or has an unexpected shape."""


def _timeout_seconds() -> float:
    raw = os.getenv("API_TENNIS_TIMEOUT")
    if raw is None or raw.strip() == "":
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise ApiTennisError(
            f"Invalid API_TENNIS_TIMEOUT value (expected number of seconds): {raw!r}"
        ) from exc
    if value <= 0:
        raise ApiTennisError("API_TENNIS_TIMEOUT must be > 0")
    return value


def _env_number(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ApiTennisError(f"Invalid {name} value (expected a number): {raw!r}") from exc
    if value < minimum:
        raise ApiTennisError(f"{name} must be >= {minimum:g}")
    return value


def _max_retries() -> int:
    return int(_env_number("API_TENNIS_MAX_RETRIES", DEFAULT_MAX_RETRIES))


_breaker: CircuitBreaker | None = None
_breaker_config: tuple[int, float] | None = None


def _circuit_breaker() -> CircuitBreaker:
    """Process-wide breaker, rebuilt only when its env configuration changes."""
    global _breaker, _breaker_config
    config = (
        int(_env_number("API_TENNIS_CIRCUIT_FAILURE_THRESHOLD", DEFAULT_CIRCUIT_FAILURE_THRESHOLD)),
        _env_number("API_TENNIS_CIRCUIT_RECOVERY_SECONDS", DEFAULT_CIRCUIT_RECOVERY_SECONDS),
    )
    if _breaker is None or _breaker_config != config:
        _breaker = CircuitBreaker(failure_threshold=config[0], recovery_seconds=config[1])
        _breaker_config = config
    return _breaker


def circuit_breaker_state() -> str:
    """Current breaker state (closed / open / half_open) for health and diagnostics."""
    return _circuit_breaker().state


def reset_circuit_breaker() -> None:
    """Forget breaker state (tests, or an operator after fixing configuration)."""
    global _breaker, _breaker_config
    _breaker = None
    _breaker_config = None


def _record_counter(name: str, labels: dict[str, str]) -> None:
    try:
        from backend.src.app.observability.metrics import record_counter

        record_counter(name, labels=labels)
    except Exception:  # metrics must never break a provider call
        logger.debug("API Tennis metric %s not recorded", name, exc_info=True)


def _record_duration(method: str, seconds: float) -> None:
    try:
        from backend.src.app.observability.metrics import record_histogram

        record_histogram(METRIC_DURATION, seconds, labels={"method": method or ""})
    except Exception:
        logger.debug("API Tennis duration metric not recorded", exc_info=True)


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


def _retry_after_seconds(response: Any) -> float | None:
    headers = getattr(response, "headers", None)
    if not isinstance(headers, dict) and not hasattr(headers, "get"):
        return None
    raw = headers.get("Retry-After")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _http_get_with_resilience(method: str, request_params: dict[str, Any], timeout: float):
    """GET with bounded retries and circuit breaker; returns an HTTP-200 response."""
    breaker = _circuit_breaker()
    max_retries = _max_retries()
    backoff_base = _env_number("API_TENNIS_RETRY_BACKOFF_SECONDS", DEFAULT_RETRY_BACKOFF_SECONDS)
    backoff_max = _env_number("API_TENNIS_RETRY_BACKOFF_MAX_SECONDS", DEFAULT_RETRY_BACKOFF_MAX_SECONDS)
    labels_method = method or ""
    attempt = 0

    while True:
        if not breaker.allow_request():
            retry_after = breaker.seconds_until_retry()
            _record_counter(METRIC_REQUESTS, {"method": labels_method, "outcome": "circuit_open"})
            logger.warning(
                "API Tennis circuit open: call rejected method=%s retry_in_s=%.0f",
                method,
                retry_after,
            )
            raise ApiTennisCircuitOpenError(
                f"API Tennis circuit breaker open (method={method})",
                retry_after_seconds=retry_after,
            )

        attempt += 1
        started = time.monotonic()
        failure: ApiTennisError
        outcome: str
        retry_after_hint: float | None = None
        try:
            response = requests.get(BASE_URL, params=request_params, timeout=timeout)
        except requests_exc.Timeout as exc:
            logger.error("API Tennis timeout method=%s timeout_s=%s", method, timeout)
            failure = ApiTennisTimeoutError(f"API Tennis timeout after {timeout}s (method={method})")
            failure.__cause__ = exc
            outcome = "timeout"
        except requests_exc.ConnectionError as exc:
            logger.error("API Tennis network error method=%s", method)
            failure = ApiTennisNetworkError(f"API Tennis network error (method={method})")
            failure.__cause__ = exc
            outcome = "network"
        except requests_exc.RequestException as exc:
            logger.error("API Tennis request failed method=%s", method)
            failure = ApiTennisNetworkError(f"API Tennis request failed (method={method})")
            failure.__cause__ = exc
            outcome = "network"
        except BaseException:
            breaker.release_probe()
            raise
        else:
            _record_duration(labels_method, time.monotonic() - started)
            if response.status_code == 200:
                if breaker.state != STATE_CLOSED:
                    _record_counter(METRIC_BREAKER_TRANSITIONS, {"state": "closed"})
                    logger.info("API Tennis circuit closed after successful probe method=%s", method)
                breaker.record_success()
                return response

            body_preview = sanitize_text(response.text, max_length=300)
            logger.error(
                "API Tennis HTTP error method=%s status=%s url=%s body=%s",
                method,
                response.status_code,
                sanitize_url(response.url),
                body_preview,
            )
            failure = ApiTennisHttpError(
                f"API Tennis HTTP {response.status_code} (method={method})",
                status_code=response.status_code,
            )
            outcome = "http_error"
            if not _is_retryable_status(response.status_code):
                # The provider answered: not an availability problem.
                breaker.record_success()
                _record_counter(METRIC_REQUESTS, {"method": labels_method, "outcome": outcome})
                raise failure
            retry_after_hint = _retry_after_seconds(response)

        if outcome != "http_error":
            _record_duration(labels_method, time.monotonic() - started)
        if breaker.record_failure():
            _record_counter(METRIC_BREAKER_TRANSITIONS, {"state": "open"})
            logger.error(
                "API Tennis circuit opened after repeated failures method=%s recovery_s=%.0f",
                method,
                breaker.recovery_seconds,
            )

        if attempt > max_retries or breaker.state != STATE_CLOSED:
            _record_counter(METRIC_REQUESTS, {"method": labels_method, "outcome": outcome})
            raise failure

        delay = backoff_delay(attempt, base_seconds=backoff_base, max_seconds=backoff_max)
        if retry_after_hint is not None:
            delay = min(max(delay, retry_after_hint), backoff_max)
        _record_counter(METRIC_RETRIES, {"method": labels_method, "reason": outcome})
        logger.warning(
            "API Tennis retry method=%s attempt=%s/%s reason=%s wait_s=%.2f",
            method,
            attempt,
            max_retries,
            outcome,
            delay,
        )
        if delay > 0:
            _sleep(delay)


def _build_request_params(
    method: str,
    params: dict | None,
    *,
    api_key: str | None = None,
) -> dict[str, Any]:
    # Never mutate the caller's dict (avoids leaking APIkey into caller logs).
    request_params: dict[str, Any] = dict(params or {})
    request_params["APIkey"] = api_key if api_key is not None else API_KEY
    request_params["method"] = method or ""
    return request_params


def _log_outgoing_request(method: str, request_params: dict[str, Any]) -> None:
    logger.info(
        "API Tennis request method=%s base=%s params=%s",
        method,
        sanitize_url(BASE_URL),
        sanitize_payload(request_params),
    )


def request_api(
    method: str,
    params: dict | None = None,
    *,
    api_key_override: str | None = None,
):
    """
    Call API-Tennis and return the `result` payload.

    Logs never include credentials (APIkey is redacted). Caller-provided
    `params` are not mutated.

    Transient failures (timeout, connection error, HTTP 429/5xx) are retried
    with exponential backoff; repeated failures open a circuit breaker and the
    call fails fast with ApiTennisCircuitOpenError (an ApiTennisNetworkError).
    """
    if not BASE_URL:
        raise ApiTennisError("API_TENNIS_BASE is not configured")
    try:
        api_key = api_key_override or resolve_api_tennis_key(
            environment_fallback=API_KEY
        )
    except RuntimeSecretError as exc:
        raise ApiTennisError(str(exc)) from exc
    if not api_key:
        raise ApiTennisError("API_TENNIS_KEY is not configured")

    request_params = _build_request_params(method, params, api_key=api_key)
    timeout = _timeout_seconds()
    _log_outgoing_request(method, request_params)

    response = _http_get_with_resilience(method, request_params, timeout)

    try:
        payload = response.json()
    except ValueError as exc:
        logger.error(
            "API Tennis invalid JSON method=%s body=%s",
            method,
            sanitize_text(response.text, max_length=300),
        )
        _record_counter(METRIC_REQUESTS, {"method": method or "", "outcome": "invalid_response"})
        raise ApiTennisInvalidResponseError(
            f"API Tennis returned invalid JSON (method={method})"
        ) from exc

    if not isinstance(payload, dict):
        logger.error(
            "API Tennis unexpected payload type method=%s type=%s",
            method,
            type(payload).__name__,
        )
        _record_counter(METRIC_REQUESTS, {"method": method or "", "outcome": "invalid_response"})
        raise ApiTennisInvalidResponseError(
            f"API Tennis returned unexpected payload type (method={method})"
        )

    response_json = payload.get("result")
    # API Tennis sometimes returns a plain error string in `result`
    # (e.g. date-range limits) instead of a list/dict payload.
    if isinstance(response_json, str):
        safe_msg = sanitize_text(response_json, max_length=300)
        logger.error("API Tennis error method=%s message=%s", method, safe_msg)
        _record_counter(METRIC_REQUESTS, {"method": method or "", "outcome": "provider_error"})
        raise ApiTennisInvalidResponseError(f"API Tennis error: {safe_msg}")
    if (
        isinstance(response_json, list)
        and response_json
        and isinstance(response_json[0], dict)
        and response_json[0].get("cod")
    ):
        error = response_json[0]
        code = error.get("cod")
        msg = sanitize_text(str(error.get("msg") or ""), max_length=300)
        logger.error(
            "API Tennis error method=%s code=%s message=%s",
            method,
            code,
            msg,
        )
        _record_counter(METRIC_REQUESTS, {"method": method or "", "outcome": "provider_error"})
        raise ApiTennisInvalidResponseError(f"API Tennis error {code}: {msg}")
    _record_counter(METRIC_REQUESTS, {"method": method or "", "outcome": "success"})
    return response_json
