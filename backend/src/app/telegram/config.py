from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[3]


class TelegramSettings(BaseSettings):
    telegram_bot_token: str | None = "8972623840:AAF1H3mKCcNzswJyJ49W5qalldhA3FveOHc"
    telegram_api_base_url: str = "http://localhost:8000/api"
    telegram_model_version: str = "v2"
    telegram_model_name: str | None = None
    telegram_default_stake: float = 10.0

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_telegram_settings() -> TelegramSettings:
    return TelegramSettings()
