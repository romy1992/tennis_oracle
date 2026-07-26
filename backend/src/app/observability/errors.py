"""Configurable error tracking without a hard dependency on a single SaaS."""

from __future__ import annotations

import logging
import threading
from typing import Any, Protocol

import httpx

from backend.src.app.observability.context import get_correlation_id
from backend.src.utility.sensitive_data import sanitize_payload, sanitize_text

logger = logging.getLogger(__name__)


class ErrorTracker(Protocol):
    def capture_exception(
        self,
        exc: BaseException,
        *,
        context: dict[str, Any] | None = None,
    ) -> None: ...

    def capture_message(
        self,
        message: str,
        *,
        level: str = "error",
        context: dict[str, Any] | None = None,
    ) -> None: ...


class NullErrorTracker:
    def capture_exception(
        self,
        exc: BaseException,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        return None

    def capture_message(
        self,
        message: str,
        *,
        level: str = "error",
        context: dict[str, Any] | None = None,
    ) -> None:
        return None


class LoggingErrorTracker:
    """Fallback tracker: structured log lines only (always available)."""

    def capture_exception(
        self,
        exc: BaseException,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        logger.error(
            "tracked_exception type=%s message=%s context=%s correlation_id=%s",
            type(exc).__name__,
            sanitize_text(str(exc)),
            sanitize_payload(context or {}),
            get_correlation_id() or "-",
            exc_info=exc,
        )

    def capture_message(
        self,
        message: str,
        *,
        level: str = "error",
        context: dict[str, Any] | None = None,
    ) -> None:
        log = getattr(logger, level.lower(), logger.error)
        log(
            "tracked_message message=%s context=%s correlation_id=%s",
            sanitize_text(message),
            sanitize_payload(context or {}),
            get_correlation_id() or "-",
        )


class WebhookErrorTracker:
    """Generic HTTP webhook (compatible with many alert/ingest endpoints)."""

    def __init__(self, url: str, *, timeout: float = 5.0) -> None:
        self._url = url
        self._timeout = timeout

    def _post(self, payload: dict[str, Any]) -> None:
        try:
            httpx.post(self._url, json=sanitize_payload(payload), timeout=self._timeout)
        except Exception:
            logger.warning("error_tracker webhook post failed", exc_info=True)

    def capture_exception(
        self,
        exc: BaseException,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        self._post(
            {
                "type": "exception",
                "exception_type": type(exc).__name__,
                "message": sanitize_text(str(exc)),
                "correlation_id": get_correlation_id(),
                "context": context or {},
            }
        )

    def capture_message(
        self,
        message: str,
        *,
        level: str = "error",
        context: dict[str, Any] | None = None,
    ) -> None:
        self._post(
            {
                "type": "message",
                "level": level,
                "message": sanitize_text(message),
                "correlation_id": get_correlation_id(),
                "context": context or {},
            }
        )


class SentryErrorTracker:
    """Optional Sentry backend (requires ``sentry-sdk`` installed separately)."""

    def __init__(self, dsn: str, *, environment: str = "local") -> None:
        try:
            import sentry_sdk  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "ERROR_TRACKING_PROVIDER=sentry requires optional package sentry-sdk"
            ) from exc
        sentry_sdk.init(dsn=dsn, environment=environment, traces_sample_rate=0.0)
        self._sentry = sentry_sdk

    def capture_exception(
        self,
        exc: BaseException,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        with self._sentry.push_scope() as scope:
            if context:
                scope.set_context("app", sanitize_payload(context))
            cid = get_correlation_id()
            if cid:
                scope.set_tag("correlation_id", cid)
            self._sentry.capture_exception(exc)

    def capture_message(
        self,
        message: str,
        *,
        level: str = "error",
        context: dict[str, Any] | None = None,
    ) -> None:
        with self._sentry.push_scope() as scope:
            if context:
                scope.set_context("app", sanitize_payload(context))
            cid = get_correlation_id()
            if cid:
                scope.set_tag("correlation_id", cid)
            self._sentry.capture_message(sanitize_text(message), level=level)


_LOCK = threading.Lock()
_TRACKER: ErrorTracker = NullErrorTracker()
_PROVIDER = "none"


def configure_error_tracking(
    *,
    provider: str = "none",
    dsn: str | None = None,
    webhook_url: str | None = None,
    environment: str = "local",
) -> ErrorTracker:
    """Select error tracker. Unknown/misconfigured providers fall back to logging."""
    global _TRACKER, _PROVIDER
    name = (provider or "none").strip().lower()
    tracker: ErrorTracker
    if name in {"", "none", "off", "disabled"}:
        tracker = NullErrorTracker()
        name = "none"
    elif name == "logging":
        tracker = LoggingErrorTracker()
    elif name == "webhook":
        url = (webhook_url or "").strip()
        if not url:
            logger.warning("ERROR_TRACKING_PROVIDER=webhook but webhook URL empty; using logging")
            tracker = LoggingErrorTracker()
            name = "logging"
        else:
            tracker = WebhookErrorTracker(url)
    elif name == "sentry":
        dsn_value = (dsn or "").strip()
        if not dsn_value:
            logger.warning("ERROR_TRACKING_PROVIDER=sentry but DSN empty; using logging")
            tracker = LoggingErrorTracker()
            name = "logging"
        else:
            try:
                tracker = SentryErrorTracker(dsn_value, environment=environment)
            except Exception:
                logger.warning("Sentry init failed; using logging tracker", exc_info=True)
                tracker = LoggingErrorTracker()
                name = "logging"
    else:
        logger.warning("Unknown ERROR_TRACKING_PROVIDER=%s; using logging", name)
        tracker = LoggingErrorTracker()
        name = "logging"

    with _LOCK:
        _TRACKER = tracker
        _PROVIDER = name
    return tracker


def get_error_tracker() -> ErrorTracker:
    return _TRACKER


def error_tracking_provider() -> str:
    return _PROVIDER


def capture_exception(exc: BaseException, *, context: dict[str, Any] | None = None) -> None:
    try:
        get_error_tracker().capture_exception(exc, context=context)
    except Exception:
        logger.debug("capture_exception failed", exc_info=True)


def capture_message(
    message: str,
    *,
    level: str = "error",
    context: dict[str, Any] | None = None,
) -> None:
    try:
        get_error_tracker().capture_message(message, level=level, context=context)
    except Exception:
        logger.debug("capture_message failed", exc_info=True)
