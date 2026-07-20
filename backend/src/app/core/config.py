from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = "local"
    debug: bool = False
    database_url: str = "postgresql://postgres:postgres@localhost:5432/tennis_db"
    api_prefix: str = "/api"
    global_update_cron_enabled: bool = False
    global_update_cron_time: str = "02:00"
    global_update_cron_timezone: str = "Europe/Rome"
    global_update_allow_concurrent_runs: bool = False
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ]
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1):\d+$"

    # Admin auth (JWT). Never commit real secrets; set via env / config.env.
    admin_jwt_secret: str = ""
    admin_jwt_expire_minutes: int = 480
    # Optional bootstrap credentials used only when admin_user table is empty.
    admin_username: str | None = None
    admin_password: str | None = None
    # Separate bot/service protection (X-Service-Token). Not an admin JWT.
    service_api_key: str | None = None
    # When SERVICE_API_KEY is empty, allow anonymous reads on bot-shared endpoints.
    allow_unauthenticated_service_reads: bool = True

    model_config = SettingsConfigDict(
        env_file=(
            ROOT_DIR / "properties" / "config.env",
            ROOT_DIR / ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
