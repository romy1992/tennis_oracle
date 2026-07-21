from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]

# Test / runtime override (middleware and non-DI callers honour this).
_settings_override: "Settings | None" = None


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
    # Set via SERVICE_API_KEY only; never hard-code. Rotate with SERVICE_API_KEY_PREVIOUS.
    service_api_key: str | None = None
    # Optional previous key accepted during rotation (SERVICE_API_KEY_PREVIOUS).
    service_api_key_previous: str | None = None
    # When SERVICE_API_KEY is empty, allow anonymous reads on bot-shared endpoints.
    allow_unauthenticated_service_reads: bool = True

    # Rate limiting (PostgreSQL-backed; shared across API replicas + Telegram bot).
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    # Per-IP for unauthenticated / public requests.
    rate_limit_public: int = 60
    # Per admin JWT fingerprint.
    rate_limit_admin: int = 300
    # Per service-token fingerprint (bot → API).
    rate_limit_internal: int = 600
    # Extra quota for expensive paths (imports, global-update, login, …).
    rate_limit_expensive: int = 20
    # Stricter public login anti-bruteforce (per IP).
    rate_limit_login: int = 10
    # Telegram bot: per telegram_user_id.
    rate_limit_telegram: int = 30
    rate_limit_telegram_expensive: int = 10

    model_config = SettingsConfigDict(
        env_file=(
            ROOT_DIR / "properties" / "config.env",
            ROOT_DIR / ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def _cached_settings() -> Settings:
    return Settings()


def get_settings() -> Settings:
    if _settings_override is not None:
        return _settings_override
    return _cached_settings()


def set_settings_override(settings: Settings | None) -> None:
    """Override settings for tests (or temporary runtime). Pass ``None`` to clear."""
    global _settings_override
    _settings_override = settings
    _cached_settings.cache_clear()
