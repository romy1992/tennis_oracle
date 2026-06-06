from fastapi import FastAPI

from backend.app.api.router import api_router
from backend.app.api.routes.health import router as health_router
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging


configure_logging()
settings = get_settings()

app = FastAPI(
    title="tennis_oracle API",
    version="0.1.0",
    debug=settings.debug,
)

app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_prefix)
