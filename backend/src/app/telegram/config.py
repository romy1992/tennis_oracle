from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[3]


class TelegramSettings(BaseSettings):
    telegram_bot_token: str | None = None
    telegram_api_base_url: str = "http://localhost:8000/api"
    # Same value as SERVICE_API_KEY on the API; sent as X-Service-Token.
    telegram_service_api_key: str | None = None
    telegram_model_version: str = "v3"
    telegram_model_name: str | None = "logistic_regression"
    telegram_default_stake: float = 10.0
    telegram_slip_count: int = 9
    telegram_min_edge_percent: float = 2.0
    # Comma-separated fallback when /models-versions/results is unavailable.
    telegram_model_names: str = "logistic_regression,random_forest"

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_telegram_settings() -> TelegramSettings:
    return TelegramSettings()
