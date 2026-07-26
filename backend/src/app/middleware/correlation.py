"""Attach / propagate correlation IDs on every HTTP request."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.src.app.observability.context import (
    CORRELATION_HEADER,
    REQUEST_ID_HEADER,
    clear_correlation_id,
    ensure_correlation_id,
)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = (
            request.headers.get(CORRELATION_HEADER)
            or request.headers.get(REQUEST_ID_HEADER)
            or request.headers.get("x-correlation-id")
            or request.headers.get("x-request-id")
        )
        correlation_id = ensure_correlation_id(incoming)
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
            response.headers[CORRELATION_HEADER] = correlation_id
            response.headers[REQUEST_ID_HEADER] = correlation_id
            return response
        finally:
            clear_correlation_id()
