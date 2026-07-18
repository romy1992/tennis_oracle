from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.src.app.api.router import api_router
from backend.src.app.api.routes.health import router as health_router
from backend.src.app.core.config import get_settings
from backend.src.app.core.logging import configure_logging
from backend.src.app.db.session import SessionLocal
from backend.src.app.scheduler import (
    start_global_update_scheduler,
    stop_global_update_scheduler,
)
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
    start_global_update_scheduler()
    yield
    stop_global_update_scheduler()


app = FastAPI(
    title="tennis_oracle API",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

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
