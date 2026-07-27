"""Telegram beta user registry: registration, whitelist, admin status transitions.

Access rules (when whitelist is enabled, default):
- ``active`` users with terms accepted (if required) may use bot commands.
- ``invited`` may complete ``/start`` and terms acceptance, but not other commands.
- ``suspended`` / ``blocked`` are denied.
When whitelist is disabled, first ``/start`` auto-activates (after terms if required).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.db.session import SessionLocal
from backend.src.app.schemas.telegram_users import (
    TelegramNotificationPreferencesUpdate,
    TelegramUserAccessResult,
    TelegramUserInviteCreate,
    TelegramUserListResponse,
    TelegramUserRead,
)
from backend.src.entity.telegram_user import TelegramUser

logger = logging.getLogger(__name__)

STATUSES = frozenset({"invited", "active", "suspended", "blocked"})
ADMIN_SETTABLE = frozenset({"invited", "active", "suspended", "blocked"})
USERNAME_MAX = 255
NAME_MAX = 255
INVITE_ORIGIN_MAX = 255


class TelegramUserError(Exception):
    """Domain error for Telegram beta users."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _truncate(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _display_name(first_name: str | None, last_name: str | None) -> str | None:
    parts = [p for p in (first_name, last_name) if p]
    return " ".join(parts) if parts else None


def _to_read(row: TelegramUser) -> TelegramUserRead:
    return TelegramUserRead.model_validate(row)


def _terms_satisfied(row: TelegramUser, settings: Settings) -> bool:
    if not settings.telegram_terms_required:
        return True
    if not row.terms_accepted:
        return False
    required_version = (settings.telegram_terms_version or "").strip()
    if not required_version:
        return True
    return (row.terms_version or "").strip() == required_version


def get_telegram_user(db: Session, telegram_user_id: int) -> TelegramUser | None:
    return db.scalar(
        select(TelegramUser).where(TelegramUser.telegram_user_id == telegram_user_id)
    )


def list_telegram_users(
    db: Session,
    *,
    q: str | None = None,
    status: str | None = None,
    telegram_user_id: int | None = None,
    username: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> TelegramUserListResponse:
    stmt = select(TelegramUser)
    count_stmt = select(func.count()).select_from(TelegramUser)

    if telegram_user_id is not None:
        stmt = stmt.where(TelegramUser.telegram_user_id == telegram_user_id)
        count_stmt = count_stmt.where(TelegramUser.telegram_user_id == telegram_user_id)
    if username:
        pattern = f"%{username.strip()}%"
        stmt = stmt.where(TelegramUser.username.ilike(pattern))
        count_stmt = count_stmt.where(TelegramUser.username.ilike(pattern))
    if status:
        cleaned = status.strip().lower()
        if cleaned not in STATUSES:
            raise TelegramUserError(f"Stato non valido: {status}", status_code=400)
        stmt = stmt.where(TelegramUser.status == cleaned)
        count_stmt = count_stmt.where(TelegramUser.status == cleaned)
    if q:
        needle = q.strip()
        if needle:
            pattern = f"%{needle}%"
            try:
                as_id = int(needle)
            except ValueError:
                as_id = None
            clauses = [
                TelegramUser.username.ilike(pattern),
                TelegramUser.first_name.ilike(pattern),
                TelegramUser.last_name.ilike(pattern),
                TelegramUser.invite_origin.ilike(pattern),
            ]
            if as_id is not None:
                clauses.append(TelegramUser.telegram_user_id == as_id)
            stmt = stmt.where(or_(*clauses))
            count_stmt = count_stmt.where(or_(*clauses))

    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        stmt.order_by(TelegramUser.last_access_at.desc(), TelegramUser.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return TelegramUserListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_to_read(row) for row in rows],
    )


def invite_telegram_user(
    db: Session,
    payload: TelegramUserInviteCreate,
) -> TelegramUserRead:
    """Pre-register or refresh an invited whitelist entry before first /start."""
    status = payload.status
    if status not in ADMIN_SETTABLE:
        raise TelegramUserError(f"Stato non valido: {status}", status_code=400)

    now = _utc_now_naive()
    existing = get_telegram_user(db, payload.telegram_user_id)
    if existing is not None:
        if payload.username is not None:
            existing.username = _truncate(payload.username, USERNAME_MAX)
        if payload.first_name is not None:
            existing.first_name = _truncate(payload.first_name, NAME_MAX)
        if payload.last_name is not None:
            existing.last_name = _truncate(payload.last_name, NAME_MAX)
        if payload.invite_origin is not None:
            existing.invite_origin = _truncate(payload.invite_origin, INVITE_ORIGIN_MAX)
        existing.status = status
        existing.updated_at = now
        db.commit()
        db.refresh(existing)
        return _to_read(existing)

    row = TelegramUser(
        telegram_user_id=payload.telegram_user_id,
        chat_id=None,
        username=_truncate(payload.username, USERNAME_MAX),
        first_name=_truncate(payload.first_name, NAME_MAX),
        last_name=_truncate(payload.last_name, NAME_MAX),
        status=status,
        invite_origin=_truncate(payload.invite_origin, INVITE_ORIGIN_MAX),
        first_access_at=now,
        last_access_at=now,
        terms_accepted=False,
        terms_accepted_at=None,
        terms_version=None,
        notifications_enabled=True,
        notify_predictions=True,
        notify_results=True,
        notify_empty_day=False,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_read(row)


def set_telegram_user_status(
    db: Session,
    telegram_user_id: int,
    *,
    status: str,
) -> TelegramUserRead:
    cleaned = (status or "").strip().lower()
    if cleaned not in ADMIN_SETTABLE:
        raise TelegramUserError(f"Stato non valido: {status}", status_code=400)
    row = get_telegram_user(db, telegram_user_id)
    if row is None:
        raise TelegramUserError("Utente Telegram non trovato.", status_code=404)
    row.status = cleaned
    row.updated_at = _utc_now_naive()
    db.commit()
    db.refresh(row)
    return _to_read(row)


def activate_telegram_user(db: Session, telegram_user_id: int) -> TelegramUserRead:
    return set_telegram_user_status(db, telegram_user_id, status="active")


def suspend_telegram_user(db: Session, telegram_user_id: int) -> TelegramUserRead:
    return set_telegram_user_status(db, telegram_user_id, status="suspended")


def block_telegram_user(db: Session, telegram_user_id: int) -> TelegramUserRead:
    return set_telegram_user_status(db, telegram_user_id, status="blocked")


def register_or_touch_on_start(
    db: Session,
    *,
    telegram_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    invite_origin: str | None = None,
    chat_id: int | None = None,
    settings: Settings | None = None,
) -> TelegramUserRead:
    """Upsert on first /start; refresh profile and last access on subsequent starts."""
    settings = settings or get_settings()
    now = _utc_now_naive()
    row = get_telegram_user(db, telegram_user_id)
    origin = _truncate(invite_origin, INVITE_ORIGIN_MAX)

    if row is None:
        if settings.telegram_whitelist_enabled:
            initial_status = "invited"
        else:
            initial_status = "active"
        row = TelegramUser(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            username=_truncate(username, USERNAME_MAX),
            first_name=_truncate(first_name, NAME_MAX),
            last_name=_truncate(last_name, NAME_MAX),
            status=initial_status,
            invite_origin=origin,
            first_access_at=now,
            last_access_at=now,
            terms_accepted=False,
            terms_accepted_at=None,
            terms_version=None,
            notifications_enabled=True,
            notify_predictions=True,
            notify_results=True,
            notify_empty_day=False,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.username = _truncate(username, USERNAME_MAX) or row.username
        row.first_name = _truncate(first_name, NAME_MAX) or row.first_name
        row.last_name = _truncate(last_name, NAME_MAX) or row.last_name
        if chat_id is not None:
            row.chat_id = chat_id
        if origin and not row.invite_origin:
            row.invite_origin = origin
        row.last_access_at = now
        row.updated_at = now
        # Open beta: promote invited → active on /start (unless suspended/blocked).
        if (
            not settings.telegram_whitelist_enabled
            and row.status == "invited"
        ):
            row.status = "active"

    db.commit()
    db.refresh(row)
    return _to_read(row)


def accept_telegram_terms(
    db: Session,
    *,
    telegram_user_id: int,
    settings: Settings | None = None,
) -> TelegramUserRead:
    settings = settings or get_settings()
    row = get_telegram_user(db, telegram_user_id)
    if row is None:
        raise TelegramUserError(
            "Utente non registrato. Usa /start prima di accettare le condizioni.",
            status_code=404,
        )
    if row.status in {"suspended", "blocked"}:
        raise TelegramUserError(
            "Account non abilitato: impossibile accettare le condizioni.",
            status_code=403,
        )
    now = _utc_now_naive()
    row.terms_accepted = True
    row.terms_accepted_at = now
    row.terms_version = (settings.telegram_terms_version or "1").strip() or "1"
    row.last_access_at = now
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return _to_read(row)


def check_telegram_access(
    db: Session,
    *,
    telegram_user_id: int,
    settings: Settings | None = None,
    touch_last_access: bool = True,
) -> TelegramUserAccessResult:
    """Centralized whitelist / terms gate used by the bot before privileged commands."""
    settings = settings or get_settings()
    row = get_telegram_user(db, telegram_user_id)

    if row is None:
        return TelegramUserAccessResult(
            allowed=False,
            status=None,
            reason="not_registered",
            terms_required=bool(settings.telegram_terms_required),
            terms_accepted=False,
            user=None,
        )

    if touch_last_access:
        row.last_access_at = _utc_now_naive()
        row.updated_at = row.last_access_at
        db.commit()
        db.refresh(row)

    terms_ok = _terms_satisfied(row, settings)
    terms_required = bool(settings.telegram_terms_required)

    if row.status == "blocked":
        return TelegramUserAccessResult(
            allowed=False,
            status=row.status,
            reason="blocked",
            terms_required=terms_required,
            terms_accepted=terms_ok,
            user=_to_read(row),
        )
    if row.status == "suspended":
        return TelegramUserAccessResult(
            allowed=False,
            status=row.status,
            reason="suspended",
            terms_required=terms_required,
            terms_accepted=terms_ok,
            user=_to_read(row),
        )
    if settings.telegram_whitelist_enabled and row.status != "active":
        return TelegramUserAccessResult(
            allowed=False,
            status=row.status,
            reason="not_active",
            terms_required=terms_required,
            terms_accepted=terms_ok,
            user=_to_read(row),
        )
    if not terms_ok:
        return TelegramUserAccessResult(
            allowed=False,
            status=row.status,
            reason="terms_required",
            terms_required=True,
            terms_accepted=False,
            user=_to_read(row),
        )

    return TelegramUserAccessResult(
        allowed=True,
        status=row.status,
        reason=None,
        terms_required=terms_required,
        terms_accepted=True,
        user=_to_read(row),
    )


def register_or_touch_on_start_safe(
    *,
    telegram_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    invite_origin: str | None = None,
    chat_id: int | None = None,
) -> TelegramUserRead | None:
    """Bot helper: never raise (analytics-style fail-open for registration)."""
    try:
        with SessionLocal() as db:
            return register_or_touch_on_start(
                db,
                telegram_user_id=telegram_user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                invite_origin=invite_origin,
                chat_id=chat_id,
            )
    except Exception:
        logger.exception(
            "Telegram user register failed telegram_user_id=%s",
            telegram_user_id,
        )
        return None


def update_notification_preferences(
    db: Session,
    *,
    telegram_user_id: int,
    payload: TelegramNotificationPreferencesUpdate,
) -> TelegramUserRead:
    """Update push preferences for a registered user (bot self-service)."""
    row = get_telegram_user(db, telegram_user_id)
    if row is None:
        raise TelegramUserError(
            "Utente non registrato. Usa /start prima di gestire le notifiche.",
            status_code=404,
        )
    if row.status in {"suspended", "blocked"}:
        raise TelegramUserError(
            "Account non abilitato: impossibile modificare le notifiche.",
            status_code=403,
        )

    changed = False
    for field in (
        "notifications_enabled",
        "notify_predictions",
        "notify_results",
        "notify_empty_day",
    ):
        value = getattr(payload, field)
        if value is not None and getattr(row, field) != value:
            setattr(row, field, value)
            changed = True

    if changed:
        row.updated_at = _utc_now_naive()
        db.commit()
        db.refresh(row)
    return _to_read(row)


def update_notification_preferences_safe(
    *,
    telegram_user_id: int,
    payload: TelegramNotificationPreferencesUpdate,
) -> TelegramUserRead | None:
    try:
        with SessionLocal() as db:
            return update_notification_preferences(
                db,
                telegram_user_id=telegram_user_id,
                payload=payload,
            )
    except TelegramUserError:
        raise
    except Exception:
        logger.exception(
            "Telegram notification prefs update failed telegram_user_id=%s",
            telegram_user_id,
        )
        return None


def get_telegram_user_safe(*, telegram_user_id: int) -> TelegramUserRead | None:
    try:
        with SessionLocal() as db:
            row = get_telegram_user(db, telegram_user_id)
            return _to_read(row) if row is not None else None
    except Exception:
        logger.exception(
            "Telegram user load failed telegram_user_id=%s",
            telegram_user_id,
        )
        return None


def check_telegram_access_safe(
    *,
    telegram_user_id: int,
    touch_last_access: bool = True,
) -> TelegramUserAccessResult:
    """Bot helper for centralized access; deny on DB errors (fail-closed for access)."""
    try:
        with SessionLocal() as db:
            return check_telegram_access(
                db,
                telegram_user_id=telegram_user_id,
                touch_last_access=touch_last_access,
            )
    except Exception:
        logger.exception(
            "Telegram access check failed telegram_user_id=%s",
            telegram_user_id,
        )
        return TelegramUserAccessResult(
            allowed=False,
            status=None,
            reason="access_check_error",
            terms_required=False,
            terms_accepted=False,
            user=None,
        )


def accept_telegram_terms_safe(
    *,
    telegram_user_id: int,
) -> TelegramUserRead | None:
    try:
        with SessionLocal() as db:
            return accept_telegram_terms(db, telegram_user_id=telegram_user_id)
    except TelegramUserError:
        raise
    except Exception:
        logger.exception(
            "Telegram terms accept failed telegram_user_id=%s",
            telegram_user_id,
        )
        return None


def access_denial_message(result: TelegramUserAccessResult) -> str:
    """Italian message for bot replies when access is denied."""
    reason = result.reason or "denied"
    if reason == "not_registered":
        return "Non sei ancora registrato. Usa /start per iniziare."
    if reason == "blocked":
        return "Il tuo accesso al bot è stato bloccato."
    if reason == "suspended":
        return "Il tuo accesso al bot è temporaneamente sospeso."
    if reason == "not_active":
        return (
            "Sei in lista di attesa (invited). "
            "Un amministratore deve attivare il tuo account beta."
        )
    if reason == "terms_required":
        return (
            "Devi accettare le condizioni d'uso prima di continuare.\n"
            "Invia /accetta_condizioni per confermare."
        )
    if reason == "access_check_error":
        return "Verifica accesso temporaneamente non disponibile. Riprova tra poco."
    return "Accesso non consentito."


def format_user_label(user: TelegramUserRead | None) -> str:
    if user is None:
        return "-"
    name = _display_name(user.first_name, user.last_name)
    if user.username and name:
        return f"@{user.username} ({name})"
    if user.username:
        return f"@{user.username}"
    if name:
        return name
    return str(user.telegram_user_id)
