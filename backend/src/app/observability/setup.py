"""Wire observability from Settings (logging, metrics, error tracking)."""

from __future__ import annotations

import logging

from backend.src.app.core.config import Settings
from backend.src.app.observability.errors import configure_error_tracking
from backend.src.app.observability.logging import configure_logging
from backend.src.app.observability.metrics import configure_metrics

logger = logging.getLogger(__name__)


def setup_observability(settings: Settings) -> None:
    configure_logging(
        debug=settings.debug,
        log_format=settings.log_format,
        force=True,
    )
    configure_metrics(settings.metrics_provider)
    configure_error_tracking(
        provider=settings.error_tracking_provider,
        dsn=settings.error_tracking_dsn,
        webhook_url=settings.error_tracking_webhook_url,
        environment=settings.app_env,
    )
    logger.info(
        "Observability ready log_format=%s metrics=%s errors=%s alerts=%s",
        settings.log_format,
        settings.metrics_provider,
        settings.error_tracking_provider,
        "on" if settings.ops_alerts_enabled else "off",
    )
