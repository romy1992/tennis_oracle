"""Structured logging (text or JSON) with correlation id and sensitive-data redaction."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from backend.src.app.observability.context import get_correlation_id
from backend.src.utility.sensitive_data import sanitize_text


class SensitiveDataFilter(logging.Filter):
    """Best-effort redaction of secrets in log messages and exception text."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = sanitize_text(record.msg, max_length=4000)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        key: _sanitize_arg(value) for key, value in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(_sanitize_arg(arg) for arg in record.args)
            if record.exc_info and record.exc_info[1] is not None:
                # Keep exception type; message path is sanitized via formatException below.
                pass
        except Exception:
            # Never break logging because of redaction failures.
            return True
        return True


def _sanitize_arg(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value, max_length=2000)
    return value


class CorrelationIdFilter(logging.Filter):
    """Inject ``correlation_id`` onto every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"
        return True


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line (compatible with most log aggregators)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_text(record.getMessage(), max_length=4000),
            "correlation_id": getattr(record, "correlation_id", None) or "-",
        }
        if record.exc_info:
            payload["exc_info"] = sanitize_text(self.formatException(record.exc_info), max_length=8000)
        if record.stack_info:
            payload["stack_info"] = sanitize_text(self.formatStack(record.stack_info), max_length=4000)
        # Extra structured fields (opt-in via logger.info("...", extra={...}))
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "correlation_id",
                "taskName",
            }:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = sanitize_text(str(value), max_length=500)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        correlation = getattr(record, "correlation_id", None) or "-"
        base = (
            f"{self.formatTime(record, self.datefmt)} {record.levelname} "
            f"[{record.name}] cid={correlation} {record.getMessage()}"
        )
        if record.exc_info:
            base = f"{base}\n{sanitize_text(self.formatException(record.exc_info), max_length=8000)}"
        return base


def configure_logging(
    *,
    debug: bool = False,
    log_format: str = "text",
    force: bool = True,
) -> None:
    """Configure root logging. Safe to call from API, bot, and CLI jobs."""
    level = logging.DEBUG if debug else logging.INFO
    fmt = (log_format or "text").strip().lower()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SensitiveDataFilter())
    handler.addFilter(CorrelationIdFilter())
    if fmt == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            TextLogFormatter(datefmt="%Y-%m-%d %H:%M:%S")
        )

    root = logging.getLogger()
    if force:
        for existing in list(root.handlers):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # Keep noisy libraries quieter in production-style runs.
    if not debug:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.INFO)
