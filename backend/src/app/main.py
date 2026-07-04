from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.src.app.api.router import api_router
from backend.src.app.api.routes.health import router as health_router
from backend.src.app.core.config import get_settings
from backend.src.app.core.logging import configure_logging


configure_logging()
settings = get_settings()

app = FastAPI(
    title="tennis_oracle API",
    version="0.1.0",
    debug=settings.debug,
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
