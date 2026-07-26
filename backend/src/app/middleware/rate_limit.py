"""HTTP rate-limit middleware (tiered, multi-instance via PostgreSQL)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.core.rate_limit import (
    consume_rate_limit,
    fingerprint_secret,
    get_rate_limit_session,
    purge_stale_buckets,
)

logger = logging.getLogger(__name__)

# Paths that skip rate limiting entirely (probes / readiness / scrape).
_EXCLUDED_PATHS = frozenset(
    {
        "/health",
        "/ready",
        "/deps",
        "/metrics",
        "/metrics.json",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
)


def client_ip(request: Request) -> str:
    """Best-effort client IP (honours first X-Forwarded-For hop when present)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return "unknown"


def classify_request(request: Request) -> tuple[str, str]:
    """Return ``(tier, bucket_key)`` for the request.

    Tiers: ``public`` (IP), ``admin`` (JWT fingerprint), ``internal`` (service token).
    """
    authorization = (request.headers.get("authorization") or "").strip()
    service_token = (request.headers.get("x-service-token") or "").strip()
    ip = client_ip(request)

    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return "admin", f"http:admin:{fingerprint_secret(token)}"

    if service_token:
        return "internal", f"http:internal:{fingerprint_secret(service_token)}"

    return "public", f"http:public:{ip}"


def limit_for_tier(settings: Settings, tier: str) -> int:
    if tier == "admin":
        return settings.rate_limit_admin
    if tier == "internal":
        return settings.rate_limit_internal
    return settings.rate_limit_public


def is_excluded_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    if normalized in _EXCLUDED_PATHS or path in _EXCLUDED_PATHS:
        return True
    # Trailing variants: /health/, /ready/, /deps/, /metrics/
    return normalized.lstrip("/") in {
        "health",
        "ready",
        "deps",
        "metrics",
        "metrics.json",
        "docs",
        "openapi.json",
        "redoc",
    }


def is_expensive_request(request: Request, api_prefix: str) -> bool:
    """True for heavy / abuse-sensitive endpoints (extra quota)."""
    path = request.url.path
    method = request.method.upper()
    prefix = (api_prefix or "/api").rstrip("/") or "/api"

    if method == "POST" and path == f"{prefix}/auth/login":
        return True
    if method == "POST" and path.startswith(f"{prefix}/global-update"):
        return True
    if method == "POST" and path.startswith(f"{prefix}/imports"):
        return True
    if method == "POST" and path.startswith(f"{prefix}/betting-slips"):
        return True
    if method == "GET" and path.startswith(f"{prefix}/single-match-value"):
        return True
    if method == "GET" and path.startswith(f"{prefix}/betting-slips/daily"):
        regenerate = request.query_params.get("regenerate", "").lower()
        if regenerate in {"1", "true", "yes"}:
            return True
    return False


def is_login_request(request: Request, api_prefix: str) -> bool:
    prefix = (api_prefix or "/api").rstrip("/") or "/api"
    return request.method.upper() == "POST" and request.url.path == f"{prefix}/auth/login"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply tiered rate limits; respond with HTTP 429 + Retry-After when exceeded."""

    def __init__(self, app: ASGIApp, settings: Settings | None = None) -> None:
        super().__init__(app)
        self._settings = settings

    def _settings_or_default(self) -> Settings:
        return self._settings or get_settings()

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = self._settings_or_default()
        if not settings.rate_limit_enabled:
            return await call_next(request)

        path = request.url.path
        if is_excluded_path(path):
            return await call_next(request)

        tier, bucket_key = classify_request(request)
        limit = limit_for_tier(settings, tier)
        window = settings.rate_limit_window_seconds

        session = get_rate_limit_session()
        try:
            try:
                decision = consume_rate_limit(
                    session,
                    bucket_key=bucket_key,
                    limit=limit,
                    window_seconds=window,
                )
            except Exception:
                session.rollback()
                logger.exception(
                    "Rate-limit check failed path=%s; allowing request (fail-open)",
                    path,
                )
                return await call_next(request)

            if not decision.allowed:
                return _too_many_requests(
                    decision.retry_after,
                    scope=tier,
                    path=path,
                    client=client_ip(request),
                )

            # Login gets an extra strict per-IP bucket (bruteforce protection).
            if is_login_request(request, settings.api_prefix):
                try:
                    login_decision = consume_rate_limit(
                        session,
                        bucket_key=f"http:login:{client_ip(request)}",
                        limit=settings.rate_limit_login,
                        window_seconds=window,
                    )
                except Exception:
                    session.rollback()
                    logger.exception(
                        "Login rate-limit check failed; allowing request (fail-open)"
                    )
                    return await call_next(request)
                if not login_decision.allowed:
                    return _too_many_requests(
                        login_decision.retry_after,
                        scope="login",
                        path=path,
                        client=client_ip(request),
                    )

            if is_expensive_request(request, settings.api_prefix):
                try:
                    expensive_decision = consume_rate_limit(
                        session,
                        bucket_key=f"http:expensive:{bucket_key}",
                        limit=settings.rate_limit_expensive,
                        window_seconds=window,
                    )
                except Exception:
                    session.rollback()
                    logger.exception(
                        "Expensive rate-limit check failed; allowing request (fail-open)"
                    )
                    return await call_next(request)
                if not expensive_decision.allowed:
                    return _too_many_requests(
                        expensive_decision.retry_after,
                        scope="expensive",
                        path=path,
                        client=client_ip(request),
                    )

            # Opportunistic cleanup of old windows (keep table small).
            if decision.hit_count == 1:
                older = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
                    seconds=max(window, 60) * 3
                )
                try:
                    purge_stale_buckets(session, older_than=older)
                except Exception:
                    session.rollback()
                    logger.debug("Rate-limit bucket purge skipped", exc_info=True)
        finally:
            session.close()

        return await call_next(request)

def _too_many_requests(
    retry_after: int,
    *,
    scope: str,
    path: str,
    client: str,
) -> JSONResponse:
    logger.warning(
        "HTTP 429 rate_limit scope=%s path=%s client_ip=%s retry_after=%s",
        scope,
        path,
        client,
        retry_after,
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please retry later.",
            "retry_after": retry_after,
        },
        headers={"Retry-After": str(max(1, retry_after))},
    )
