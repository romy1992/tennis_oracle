"""Configurable outbound Telegram notifications (daily predictions / results / empty).

Admin pipeline alerts stay in ``observability.alerts`` / ``notify``; this module
handles end-user fan-out with durable dedupe, controlled retry, and delivery logging.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Literal

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.services.predictions import (
    compute_daily_prediction_stats,
    get_next_fixtures_with_predictions,
)
from backend.src.app.services.telegram_users import _terms_satisfied
from backend.src.app.telegram.dates import today_rome
from backend.src.app.telegram.messages import (
    format_fixtures_empty,
    format_notification_predictions,
    format_notification_results,
    split_message,
)
from backend.src.entity.telegram_notification_delivery import TelegramNotificationDelivery
from backend.src.entity.telegram_user import TelegramUser
from backend.src.utility.sensitive_data import sanitize_text

logger = logging.getLogger(__name__)

NotificationKind = Literal["predictions", "results", "empty_day"]
KIND_PREDICTIONS: NotificationKind = "predictions"
KIND_RESULTS: NotificationKind = "results"
KIND_EMPTY_DAY: NotificationKind = "empty_day"
ALL_KINDS: tuple[NotificationKind, ...] = (
    KIND_PREDICTIONS,
    KIND_RESULTS,
    KIND_EMPTY_DAY,
)

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

# Permanent Telegram API failures (do not retry).
_PERMANENT_ERROR_CODES = frozenset({400, 401, 403, 404})


@dataclass
class DeliverySendResult:
    status: str
    attempt_count: int = 0
    telegram_message_id: int | None = None
    error: str | None = None
    skipped_reason: str | None = None


@dataclass
class NotificationRunSummary:
    kind: str
    content_date: date
    recipients: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    dry_run: bool = False
    message_preview: str | None = None
    details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "content_date": self.content_date.isoformat(),
            "recipients": self.recipients,
            "sent": self.sent,
            "failed": self.failed,
            "skipped": self.skipped,
            "dry_run": self.dry_run,
            "message_preview": self.message_preview,
            "details": self.details,
        }


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_dedupe_key(kind: str, content_date: date, telegram_user_id: int) -> str:
    return f"{kind}:{content_date.isoformat()}:{telegram_user_id}"


def list_notification_recipients(
    db: Session,
    *,
    kind: NotificationKind,
    settings: Settings | None = None,
) -> list[TelegramUser]:
    """Active users with chat_id, master switch on, kind preference on; skip suspended."""
    settings = settings or get_settings()
    stmt = (
        select(TelegramUser)
        .where(TelegramUser.status == "active")
        .where(TelegramUser.notifications_enabled.is_(True))
        .where(TelegramUser.chat_id.is_not(None))
        .order_by(TelegramUser.id.asc())
    )
    if kind == KIND_PREDICTIONS:
        stmt = stmt.where(TelegramUser.notify_predictions.is_(True))
    elif kind == KIND_RESULTS:
        stmt = stmt.where(TelegramUser.notify_results.is_(True))
    elif kind == KIND_EMPTY_DAY:
        stmt = stmt.where(TelegramUser.notify_empty_day.is_(True))
    else:
        raise ValueError(f"Unknown notification kind: {kind}")

    rows = list(db.scalars(stmt).all())
    return [row for row in rows if _terms_satisfied(row, settings)]


def build_predictions_message(
    db: Session,
    *,
    target_date: date,
    settings: Settings | None = None,
    model_version: str | None = None,
    model_name: str | None = None,
) -> tuple[str, int]:
    """Return (message text, fixture count) for today's predictions push."""
    settings = settings or get_settings()
    version = (model_version or settings.public_model_version or "v3").strip() or "v3"
    name = model_name if model_name is not None else settings.public_model_name
    page = get_next_fixtures_with_predictions(
        db,
        model_version=version,  # type: ignore[arg-type]
        model_name=name,
        from_date=target_date,
        to_date=target_date,
        limit=200,
        offset=0,
        status="upcoming",
    )
    items = [item.model_dump(mode="json") for item in page.items]
    if not items:
        return format_fixtures_empty(target_date), 0
    return format_notification_predictions(items, target_date), len(items)


def build_results_message(
    db: Session,
    *,
    target_date: date,
    settings: Settings | None = None,
    model_version: str | None = None,
    model_name: str | None = None,
) -> str:
    """Results digest for a settled day (typically yesterday Rome)."""
    settings = settings or get_settings()
    version = (model_version or settings.public_model_version or "v3").strip() or "v3"
    name = model_name if model_name is not None else settings.public_model_name
    day_offset = (today_rome() - target_date).days
    if day_offset < 0:
        day_offset = 0
    stats = compute_daily_prediction_stats(
        db,
        model_version=version,  # type: ignore[arg-type]
        model_name=name,
        from_day=day_offset,
        to_day=day_offset,
        reference_date=today_rome(),
    )
    day = stats.days[0] if stats.days else None
    payload = day.model_dump(mode="json") if day is not None else None
    return format_notification_results(target_date, payload)


def build_empty_day_message(*, target_date: date) -> str:
    return format_fixtures_empty(target_date)


def _get_or_create_delivery(
    db: Session,
    *,
    kind: str,
    content_date: date,
    telegram_user_id: int,
    chat_id: int | None,
) -> TelegramNotificationDelivery:
    dedupe_key = make_dedupe_key(kind, content_date, telegram_user_id)
    existing = db.scalar(
        select(TelegramNotificationDelivery).where(
            TelegramNotificationDelivery.dedupe_key == dedupe_key
        )
    )
    if existing is not None:
        return existing

    now = _utc_now_naive()
    row = TelegramNotificationDelivery(
        dedupe_key=dedupe_key,
        kind=kind,
        content_date=content_date,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        status=STATUS_PENDING,
        attempt_count=0,
        telegram_message_id=None,
        last_error=None,
        created_at=now,
        updated_at=now,
        sent_at=None,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(TelegramNotificationDelivery).where(
                TelegramNotificationDelivery.dedupe_key == dedupe_key
            )
        )
        if existing is None:
            raise
        return existing
    db.refresh(row)
    return row


def _mark_delivery(
    db: Session,
    row: TelegramNotificationDelivery,
    *,
    status: str,
    attempt_count: int | None = None,
    telegram_message_id: int | None = None,
    last_error: str | None = None,
    sent_at: datetime | None = None,
) -> TelegramNotificationDelivery:
    row.status = status
    if attempt_count is not None:
        row.attempt_count = attempt_count
    if telegram_message_id is not None:
        row.telegram_message_id = telegram_message_id
    row.last_error = last_error
    row.updated_at = _utc_now_naive()
    if sent_at is not None:
        row.sent_at = sent_at
    db.commit()
    db.refresh(row)
    return row


def send_telegram_message(
    *,
    bot_token: str,
    chat_id: int,
    text: str,
    timeout: float = 15.0,
    http_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Send one text message via Bot API. Raises httpx.HTTPStatusError on HTTP errors."""
    chunks = split_message(text)
    body = chunks[0] if chunks else text
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    poster = http_post or httpx.post
    response = poster(
        url,
        json={
            "chat_id": chat_id,
            "text": body,
            "disable_web_page_preview": True,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json() if hasattr(response, "json") else {}
    return payload if isinstance(payload, dict) else {}


def _retry_after_seconds(response: httpx.Response | None, fallback: float) -> float:
    if response is None:
        return fallback
    header = response.headers.get("Retry-After") if response.headers else None
    if header:
        try:
            return max(float(header), 0.1)
        except ValueError:
            pass
    try:
        payload = response.json()
        params = payload.get("parameters") if isinstance(payload, dict) else None
        if isinstance(params, dict) and params.get("retry_after") is not None:
            return max(float(params["retry_after"]), 0.1)
    except Exception:
        pass
    return fallback


def deliver_to_user(
    db: Session,
    *,
    user: TelegramUser,
    kind: NotificationKind,
    content_date: date,
    message: str,
    bot_token: str,
    max_retries: int,
    retry_backoff_seconds: float,
    dry_run: bool = False,
    force: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
    http_post: Callable[..., Any] | None = None,
) -> DeliverySendResult:
    """Send one notification with durable dedupe and controlled retries."""
    chat_id = user.chat_id
    if chat_id is None:
        return DeliverySendResult(status=STATUS_SKIPPED, skipped_reason="missing_chat_id")

    row = _get_or_create_delivery(
        db,
        kind=kind,
        content_date=content_date,
        telegram_user_id=user.telegram_user_id,
        chat_id=chat_id,
    )
    if row.status == STATUS_SENT and not force:
        return DeliverySendResult(
            status=STATUS_SKIPPED,
            attempt_count=row.attempt_count,
            telegram_message_id=row.telegram_message_id,
            skipped_reason="already_sent",
        )
    if row.status == STATUS_SKIPPED and row.last_error == "permanent" and not force:
        return DeliverySendResult(
            status=STATUS_SKIPPED,
            attempt_count=row.attempt_count,
            skipped_reason="permanent_failure",
            error=row.last_error,
        )

    if dry_run:
        _mark_delivery(
            db,
            row,
            status=STATUS_SKIPPED,
            attempt_count=row.attempt_count,
            last_error="dry_run",
        )
        return DeliverySendResult(status=STATUS_SKIPPED, skipped_reason="dry_run")

    attempts = 0
    last_error: str | None = None
    max_attempts = max(1, max_retries + 1)

    while attempts < max_attempts:
        attempts += 1
        try:
            payload = send_telegram_message(
                bot_token=bot_token,
                chat_id=int(chat_id),
                text=message,
                http_post=http_post,
            )
            result = payload.get("result") if isinstance(payload, dict) else None
            message_id = None
            if isinstance(result, dict) and result.get("message_id") is not None:
                message_id = int(result["message_id"])
            _mark_delivery(
                db,
                row,
                status=STATUS_SENT,
                attempt_count=attempts,
                telegram_message_id=message_id,
                last_error=None,
                sent_at=_utc_now_naive(),
            )
            return DeliverySendResult(
                status=STATUS_SENT,
                attempt_count=attempts,
                telegram_message_id=message_id,
            )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            detail = sanitize_text(str(exc), max_length=400)
            last_error = f"http_{status_code}:{detail}"
            if status_code in _PERMANENT_ERROR_CODES:
                _mark_delivery(
                    db,
                    row,
                    status=STATUS_FAILED,
                    attempt_count=attempts,
                    last_error=f"permanent:{last_error}",
                )
                return DeliverySendResult(
                    status=STATUS_FAILED,
                    attempt_count=attempts,
                    error=last_error,
                )
            if attempts >= max_attempts:
                break
            wait = _retry_after_seconds(
                exc.response,
                retry_backoff_seconds * attempts,
            )
            sleep_fn(wait)
        except Exception as exc:
            last_error = sanitize_text(str(exc), max_length=400)
            if attempts >= max_attempts:
                break
            sleep_fn(retry_backoff_seconds * attempts)

    _mark_delivery(
        db,
        row,
        status=STATUS_FAILED,
        attempt_count=attempts,
        last_error=last_error,
    )
    return DeliverySendResult(
        status=STATUS_FAILED,
        attempt_count=attempts,
        error=last_error,
    )


def run_notification_kind(
    db: Session,
    *,
    kind: NotificationKind,
    content_date: date | None = None,
    settings: Settings | None = None,
    dry_run: bool = False,
    force: bool = False,
    model_version: str | None = None,
    model_name: str | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    http_post: Callable[..., Any] | None = None,
) -> NotificationRunSummary:
    """Build message for ``kind`` and fan-out to eligible recipients."""
    settings = settings or get_settings()
    today = today_rome()
    resolved_date = content_date or (
        today - timedelta(days=1) if kind == KIND_RESULTS else today
    )

    summary = NotificationRunSummary(
        kind=kind,
        content_date=resolved_date,
        dry_run=dry_run,
    )

    if not settings.telegram_notifications_enabled:
        summary.message_preview = "notifications_disabled"
        return summary

    kind_enabled = {
        KIND_PREDICTIONS: settings.telegram_notify_predictions_enabled,
        KIND_RESULTS: settings.telegram_notify_results_enabled,
        KIND_EMPTY_DAY: settings.telegram_notify_empty_day_enabled,
    }
    if not kind_enabled.get(kind, False):
        summary.message_preview = f"kind_disabled:{kind}"
        return summary

    token = (settings.telegram_bot_token or "").strip()
    if not token and not dry_run:
        summary.message_preview = "missing_bot_token"
        logger.warning("Telegram notifications skipped: TELEGRAM_BOT_TOKEN missing")
        return summary

    if kind == KIND_PREDICTIONS:
        message, count = build_predictions_message(
            db,
            target_date=resolved_date,
            settings=settings,
            model_version=model_version,
            model_name=model_name,
        )
        if count == 0:
            # Predictions job does not send empty; empty_day is a separate kind.
            summary.message_preview = "no_fixtures"
            return summary
    elif kind == KIND_EMPTY_DAY:
        message, count = build_predictions_message(
            db,
            target_date=resolved_date,
            settings=settings,
            model_version=model_version,
            model_name=model_name,
        )
        if count > 0:
            summary.message_preview = "fixtures_present"
            return summary
        message = build_empty_day_message(target_date=resolved_date)
    else:
        message = build_results_message(
            db,
            target_date=resolved_date,
            settings=settings,
            model_version=model_version,
            model_name=model_name,
        )

    summary.message_preview = sanitize_text(message, max_length=240)
    recipients = list_notification_recipients(db, kind=kind, settings=settings)
    summary.recipients = len(recipients)

    min_interval = max(0.0, float(settings.telegram_notify_min_interval_seconds))
    for index, user in enumerate(recipients):
        if index > 0 and min_interval > 0:
            sleep_fn(min_interval)
        result = deliver_to_user(
            db,
            user=user,
            kind=kind,
            content_date=resolved_date,
            message=message,
            bot_token=token or "dry-run",
            max_retries=settings.telegram_notify_max_retries,
            retry_backoff_seconds=settings.telegram_notify_retry_backoff_seconds,
            dry_run=dry_run,
            force=force,
            sleep_fn=sleep_fn,
            http_post=http_post,
        )
        detail = {
            "telegram_user_id": user.telegram_user_id,
            "status": result.status,
            "attempt_count": result.attempt_count,
            "skipped_reason": result.skipped_reason,
            "error": result.error,
        }
        summary.details.append(detail)
        if result.status == STATUS_SENT:
            summary.sent += 1
        elif result.status == STATUS_FAILED:
            summary.failed += 1
        else:
            summary.skipped += 1

    return summary


def run_daily_telegram_notifications(
    db: Session,
    *,
    kinds: list[NotificationKind] | None = None,
    content_date: date | None = None,
    results_date: date | None = None,
    settings: Settings | None = None,
    dry_run: bool = False,
    force: bool = False,
    model_version: str | None = None,
    model_name: str | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    http_post: Callable[..., Any] | None = None,
) -> list[NotificationRunSummary]:
    """Run configured notification kinds (default: predictions + empty_day + results)."""
    settings = settings or get_settings()
    selected = kinds or list(ALL_KINDS)
    summaries: list[NotificationRunSummary] = []
    today = content_date or today_rome()
    yesterday = results_date or (today - timedelta(days=1))

    for kind in selected:
        target = yesterday if kind == KIND_RESULTS else today
        summaries.append(
            run_notification_kind(
                db,
                kind=kind,
                content_date=target,
                settings=settings,
                dry_run=dry_run,
                force=force,
                model_version=model_version,
                model_name=model_name,
                sleep_fn=sleep_fn,
                http_post=http_post,
            )
        )
    return summaries
