"""Optional metrics scrape / JSON snapshot endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from fastapi.responses import PlainTextResponse

from backend.src.app.core.config import get_settings
from backend.src.app.observability.metrics import (
    get_metrics,
    metrics_enabled,
    metrics_provider,
)

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics() -> Response:
    settings = get_settings()
    if not settings.metrics_endpoint_enabled or not metrics_enabled():
        return Response(
            content='{"detail":"metrics endpoint disabled"}',
            status_code=status.HTTP_404_NOT_FOUND,
            media_type="application/json",
        )
    registry = get_metrics()
    provider = metrics_provider()
    if provider == "prometheus" or provider == "memory":
        # Prometheus text is the portable scrape format; JSON available via Accept.
        return PlainTextResponse(
            content=registry.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    return Response(
        content='{"detail":"metrics endpoint disabled"}',
        status_code=status.HTTP_404_NOT_FOUND,
        media_type="application/json",
    )


@router.get("/metrics.json")
def metrics_json() -> dict:
    settings = get_settings()
    if not settings.metrics_endpoint_enabled or not metrics_enabled():
        return {"status": "disabled"}
    return {"provider": metrics_provider(), **get_metrics().snapshot()}
