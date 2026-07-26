"""Record HTTP request counts and latency histograms."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.src.app.observability.metrics import metrics_enabled, record_counter, record_histogram

_SKIP_PREFIXES = ("/health", "/ready", "/deps", "/metrics", "/docs", "/openapi.json", "/redoc")


def _should_skip(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    for prefix in _SKIP_PREFIXES:
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


class MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not metrics_enabled() or _should_skip(request.url.path):
            return await call_next(request)

        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - started
            # Low-cardinality labels only (method + status class + coarse path).
            path = _normalize_path(request.url.path)
            labels = {
                "method": request.method.upper(),
                "status": str(status_code),
                "path": path,
            }
            record_counter("http_requests_total", labels=labels)
            record_histogram("http_request_duration_seconds", elapsed, labels=labels)


def _normalize_path(path: str) -> str:
    """Collapse numeric path segments to reduce cardinality."""
    parts = []
    for part in path.split("/"):
        if not part:
            continue
        if part.isdigit():
            parts.append("{id}")
        else:
            parts.append(part[:64])
    return "/" + "/".join(parts) if parts else "/"
