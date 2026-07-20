"""Centralized redaction of credentials and other sensitive values for logs."""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

REDACTED = "***"

# Case-insensitive key / query-param names to mask (normalized: lower, '-' -> '_').
_SENSITIVE_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "passwd",
        "secret",
        "authorization",
        "cookie",
        "set_cookie",
        "x_api_key",
        "telegram_bot_token",
        "bot_token",
    }
)

# Compact forms without underscores (covers APIkey, api-key, api_key, etc.).
_SENSITIVE_COMPACT = frozenset(
    {
        "apikey",
        "apitoken",
        "accesstoken",
        "refreshtoken",
        "password",
        "passwd",
        "secret",
        "authorization",
        "cookie",
        "setcookie",
        "xapikey",
        "telegrambottoken",
        "bottoken",
        "token",
    }
)

# Free-text patterns: APIkey=..., token: ..., password=...
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|access[_-]?token|refresh[_-]?token|password|passwd|secret|"
    r"authorization|cookie|bot[_-]?token|telegram[_-]?bot[_-]?token)\b\s*([=:])\s*([^\s&;,\"']+)"
)


def _is_sensitive_key(key: Any) -> bool:
    if key is None:
        return False
    normalized = str(key).strip().lower().replace("-", "_")
    compact = normalized.replace("_", "")
    return normalized in _SENSITIVE_KEYS or compact in _SENSITIVE_COMPACT


def _encode_query_pair(key: str, value: str) -> str:
    """Encode a query pair; keep redaction marker readable in logs."""
    encoded_key = quote(str(key), safe="")
    if value == REDACTED:
        return f"{encoded_key}={REDACTED}"
    return f"{encoded_key}={quote(str(value), safe='')}"


def sanitize_url(url: str | None) -> str:
    """Mask userinfo and sensitive query parameters in a URL."""
    if not url:
        return ""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return REDACTED

    netloc = parts.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        if ":" in userinfo:
            username, _ = userinfo.split(":", 1)
            netloc = f"{username}:{REDACTED}@{host}"
        else:
            netloc = f"{REDACTED}@{host}"

    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    sanitized_query = "&".join(
        _encode_query_pair(key, REDACTED if _is_sensitive_key(key) else value)
        for key, value in query_pairs
    )
    return urlunsplit(
        (parts.scheme, netloc, parts.path, sanitized_query, parts.fragment)
    )


def sanitize_headers(headers: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copy of headers with sensitive values redacted."""
    if not headers:
        return {}
    return {
        str(key): (REDACTED if _is_sensitive_key(key) else value)
        for key, value in headers.items()
    }


def sanitize_payload(value: Any, *, max_depth: int = 8) -> Any:
    """Recursively redact sensitive keys in dict/list payloads."""
    if max_depth < 0:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(key): (
                REDACTED
                if _is_sensitive_key(key)
                else sanitize_payload(item, max_depth=max_depth - 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_payload(item, max_depth=max_depth - 1) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_payload(item, max_depth=max_depth - 1) for item in value)
    return value


def sanitize_text(text: str | None, *, max_length: int = 500) -> str:
    """Best-effort redaction for free-form response/error text."""
    if not text:
        return ""
    sanitized = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        str(text),
    )

    lowered = sanitized.lower()
    for marker in ("authorization:", "bearer ", "cookie:"):
        idx = lowered.find(marker)
        if idx >= 0:
            end = idx + len(marker)
            sanitized = sanitized[:end] + f" {REDACTED}"
            lowered = sanitized.lower()

    if len(sanitized) > max_length:
        return sanitized[:max_length] + "...(truncated)"
    return sanitized
