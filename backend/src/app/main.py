from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.src.app.api.router import api_router
from backend.src.app.api.routes.health import router as health_router
from backend.src.app.core.config import get_settings
from backend.src.app.core.logging import configure_logging
from backend.src.app.db.session import SessionLocal
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

# Rate limiting first in the stack (executed last on the way in) so CORS
# preflight and normal responses still get CORS headers on 429.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_prefix)
