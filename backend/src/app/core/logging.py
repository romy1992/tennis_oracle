"""Backward-compatible entrypoint; delegates to observability.setup."""

from backend.src.app.core.config import get_settings
from backend.src.app.observability.setup import setup_observability


def configure_logging() -> None:
    setup_observability(get_settings())
