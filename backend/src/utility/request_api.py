"""HTTP client for the external tennis API (API-Tennis)."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests
from requests import exceptions as requests_exc

from backend.src.app.core.env_files import load_backend_env_files
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


class ApiTennisError(RuntimeError):
    """Base error for API-Tennis client failures (safe for logging)."""


class ApiTennisTimeoutError(ApiTennisError):
    """Request exceeded the configured timeout."""


class ApiTennisNetworkError(ApiTennisError):
    """Network / connection failure talking to API-Tennis."""


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


def _build_request_params(method: str, params: dict | None) -> dict[str, Any]:
    # Never mutate the caller's dict (avoids leaking APIkey into caller logs).
    request_params: dict[str, Any] = dict(params or {})
    request_params["APIkey"] = API_KEY
    request_params["method"] = method or ""
    return request_params


def _log_outgoing_request(method: str, request_params: dict[str, Any]) -> None:
    logger.info(
        "API Tennis request method=%s base=%s params=%s",
        method,
        sanitize_url(BASE_URL),
        sanitize_payload(request_params),
    )


def request_api(method: str, params: dict | None = None):
    """
    Call API-Tennis and return the `result` payload.

    Logs never include credentials (APIkey is redacted). Caller-provided
    `params` are not mutated.
    """
    if not BASE_URL:
        raise ApiTennisError("API_TENNIS_BASE is not configured")
    if not API_KEY:
        raise ApiTennisError("API_TENNIS_KEY is not configured")

    request_params = _build_request_params(method, params)
    timeout = _timeout_seconds()
    _log_outgoing_request(method, request_params)

    try:
        response = requests.get(BASE_URL, params=request_params, timeout=timeout)
    except requests_exc.Timeout as exc:
        logger.error(
            "API Tennis timeout method=%s timeout_s=%s",
            method,
            timeout,
        )
        raise ApiTennisTimeoutError(
            f"API Tennis timeout after {timeout}s (method={method})"
        ) from exc
    except requests_exc.ConnectionError as exc:
        logger.error("API Tennis network error method=%s", method)
        raise ApiTennisNetworkError(
            f"API Tennis network error (method={method})"
        ) from exc
    except requests_exc.RequestException as exc:
        logger.error("API Tennis request failed method=%s", method)
        raise ApiTennisNetworkError(
            f"API Tennis request failed (method={method})"
        ) from exc

    if response.status_code != 200:
        body_preview = sanitize_text(response.text, max_length=300)
        logger.error(
            "API Tennis HTTP error method=%s status=%s url=%s body=%s",
            method,
            response.status_code,
            sanitize_url(response.url),
            body_preview,
        )
        raise ApiTennisHttpError(
            f"API Tennis HTTP {response.status_code} (method={method})",
            status_code=response.status_code,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        logger.error(
            "API Tennis invalid JSON method=%s body=%s",
            method,
            sanitize_text(response.text, max_length=300),
        )
        raise ApiTennisInvalidResponseError(
            f"API Tennis returned invalid JSON (method={method})"
        ) from exc

    if not isinstance(payload, dict):
        logger.error(
            "API Tennis unexpected payload type method=%s type=%s",
            method,
            type(payload).__name__,
        )
        raise ApiTennisInvalidResponseError(
            f"API Tennis returned unexpected payload type (method={method})"
        )

    response_json = payload.get("result")
    # API Tennis sometimes returns a plain error string in `result`
    # (e.g. date-range limits) instead of a list/dict payload.
    if isinstance(response_json, str):
        safe_msg = sanitize_text(response_json, max_length=300)
        logger.error("API Tennis error method=%s message=%s", method, safe_msg)
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
        raise ApiTennisInvalidResponseError(f"API Tennis error {code}: {msg}")
    return response_json
