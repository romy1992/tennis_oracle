from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.src.app.api.router import api_router
from backend.src.app.api.routes.health import router as health_router
from backend.src.app.api.routes.metrics import router as metrics_router
from backend.src.app.core.config import get_settings
from backend.src.app.core.logging import configure_logging
from backend.src.app.db.session import SessionLocal
from backend.src.app.middleware.correlation import CorrelationIdMiddleware
from backend.src.app.middleware.metrics import MetricsMiddleware
from backend.src.app.middleware.rate_limit import RateLimitMiddleware
from backend.src.app.scheduler import (
    start_global_update_scheduler,
    stop_global_update_scheduler,
)
from backend.src.app.services.auth import ensure_bootstrap_admin
from backend.src.app.services.global_update import reconcile_orphaned_runs


configure_logging()
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with SessionLocal() as db:
        reconciled = reconcile_orphaned_runs(db)
        if reconciled:
            import logging

            logging.getLogger(__name__).info(
                "Reconciled %s orphaned global update run(s) on startup.",
                reconciled,
            )
        try:
            ensure_bootstrap_admin(db, settings)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Failed to bootstrap admin user from environment."
            )
    start_global_update_scheduler()
    yield
    stop_global_update_scheduler()


app = FastAPI(
    title="tennis_oracle API",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

# Outer → inner on the way in: CORS → rate limit → metrics → correlation → app.
# Rate limiting before CORS would strip CORS headers on 429; keep rate limit
# inside CORS. Correlation innermost so request handlers see the id.
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RateLimitMiddleware)
# Empty CORS_ORIGIN_REGEX (common in staging/prod) must be None, not "".
_cors_origin_regex = (settings.cors_origin_regex or "").strip() or None
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "X-Request-ID"],
)

app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(api_router, prefix=settings.api_prefix)
