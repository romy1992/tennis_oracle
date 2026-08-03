from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[3]
BACKEND_ENV_FILE = BACKEND_DIR / ".env"
BACKEND_CONFIG_ENV_FILE = BACKEND_DIR / "properties" / "config.env"


def load_backend_env_files(*, override: bool = False) -> None:
    """Load backend env files with backend/.env as primary and config.env as fallback."""
    load_dotenv(dotenv_path=BACKEND_ENV_FILE, override=override)
    load_dotenv(dotenv_path=BACKEND_CONFIG_ENV_FILE, override=override)

