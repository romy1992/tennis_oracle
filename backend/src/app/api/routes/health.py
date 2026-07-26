from fastapi import APIRouter, Response, status
from sqlalchemy import text

from backend.src.app.core.config import get_settings
from backend.src.app.db.session import SessionLocal
from backend.src.app.observability.dependencies import build_dependencies_status


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str | bool]:
    """Liveness: process is up (no dependency checks)."""
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.app_env,
        "debug": settings.debug,
    }


@router.get("/ready")
def ready(response: Response) -> dict[str, str | bool]:
    """Readiness: app can serve traffic (database reachable)."""
    settings = get_settings()
    database = "ok"
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        database = "error"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "environment": settings.app_env,
            "debug": settings.debug,
            "database": database,
        }
    return {
        "status": "ready",
        "environment": settings.app_env,
        "debug": settings.debug,
        "database": database,
    }


@router.get("/deps")
def dependencies(response: Response) -> dict:
    """Dependency status for operators (DB + monitoring channels; no secrets)."""
    settings = get_settings()
    database_status: dict
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            database_status = {"status": "ok"}
            payload = build_dependencies_status(
                settings, database_status=database_status
            )
    except Exception as exc:
        database_status = {"status": "error", "error": type(exc).__name__}
        payload = build_dependencies_status(settings, database_status=database_status)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    if payload.get("status") != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload
