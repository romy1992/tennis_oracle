"""Resend HTTPS delivery for scheduled operational reports."""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx

from backend.src.app.core.config import Settings
from backend.src.utility.sensitive_data import sanitize_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailAttachment:
    """One in-memory or filesystem report attachment."""

    filename: str
    content: bytes

    @classmethod
    def from_path(cls, path: str | Path) -> "EmailAttachment | None":
        candidate = Path(path)
        if not candidate.is_file():
            return None
        return cls(
            filename=candidate.name,
            content=candidate.read_bytes(),
        )


def _recipients(raw: str) -> list[str]:
    normalized = raw.replace(";", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def validate_email_settings(settings: Settings) -> list[str]:
    """Return missing/invalid fields without exposing any credential value."""
    if not settings.report_email_enabled:
        return []
    missing: list[str] = []
    if not _recipients(settings.report_email_to):
        missing.append("REPORT_EMAIL_TO")
    if not (settings.resend_api_key or "").strip():
        missing.append("RESEND_API_KEY")
    if not (settings.resend_api_base or "").strip():
        missing.append("RESEND_API_BASE")
    if not (settings.resend_from or "").strip():
        missing.append("RESEND_FROM")
    return missing


def _idempotency_key(
    *,
    sender: str,
    recipients: list[str],
    subject: str,
    body: str,
    attachments: list[EmailAttachment],
) -> str:
    digest = hashlib.sha256()
    for value in (sender, *recipients, subject, body):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    for attachment in attachments:
        digest.update(attachment.filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(attachment.content)
        digest.update(b"\0")
    return f"tennis-oracle-{digest.hexdigest()}"


def send_report_email(
    settings: Settings,
    *,
    subject: str,
    body: str,
    attachments: Iterable[EmailAttachment] = (),
) -> dict[str, str | bool | int]:
    """Send one report email.

    The caller receives a structured result so pipeline status and email
    delivery can be recorded independently. Credential values are never
    included in errors or logs.
    """
    result: dict[str, str | bool | int] = {
        "sent": False,
        "skipped": False,
        "status": "pending",
        "recipients": 0,
    }
    if not settings.report_email_enabled:
        result.update(skipped=True, status="disabled")
        return result

    missing = validate_email_settings(settings)
    if missing:
        result.update(status="configuration_error", error="missing: " + ", ".join(missing))
        logger.error("Scheduled report email configuration incomplete: %s", ", ".join(missing))
        return result

    recipients = _recipients(settings.report_email_to)
    sender = (settings.resend_from or "").strip()
    attachment_list = list(attachments)
    payload: dict[str, object] = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "text": body,
    }
    if attachment_list:
        payload["attachments"] = [
            {
                "filename": attachment.filename,
                "content": base64.b64encode(attachment.content).decode("ascii"),
            }
            for attachment in attachment_list
        ]
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
        "User-Agent": "tennis-oracle-scheduler/1.0",
        "Idempotency-Key": _idempotency_key(
            sender=sender,
            recipients=recipients,
            subject=subject,
            body=body,
            attachments=attachment_list,
        ),
    }
    endpoint = f"{settings.resend_api_base.rstrip('/')}" + "/emails"

    try:
        with httpx.Client(timeout=settings.resend_timeout_seconds) as client:
            response = client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            response_payload = response.json()
            provider_message_id = str(response_payload.get("id") or "").strip()
    except Exception as exc:
        safe_error = sanitize_text(f"{type(exc).__name__}: {exc}", max_length=500)
        api_key = settings.resend_api_key or ""
        if api_key:
            safe_error = safe_error.replace(api_key, "***")
        result.update(status="error", error=safe_error, recipients=len(recipients))
        logger.error("Scheduled report Resend delivery failed: %s", safe_error)
        return result

    result.update(sent=True, status="sent", recipients=len(recipients))
    if provider_message_id:
        result["provider_message_id"] = provider_message_id
    logger.info(
        "Scheduled report email sent via Resend recipients=%s subject=%s",
        len(recipients),
        subject,
    )
    return result
