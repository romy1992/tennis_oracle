"""Runtime feature flags stored in DB and editable from admin dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.db.session import SessionLocal
from backend.src.app.schemas.feature_flags import FeatureFlagRead
from backend.src.entity.feature_flag import FeatureFlag

logger = logging.getLogger(__name__)

FEATURE_TELEGRAM_SUBSCRIPTIONS = "telegram.subscriptions_enabled"
FEATURE_TELEGRAM_STATISTICS = "telegram.statistics_enabled"
FEATURE_TELEGRAM_NOTIFICATIONS = "telegram.notifications_enabled"
FEATURE_TELEGRAM_AUTHORIZATIONS = "telegram.authorizations_enabled"
FEATURE_TELEGRAM_FIXTURES = "telegram.fixtures_enabled"
FEATURE_TELEGRAM_SLIPS = "telegram.slips_enabled"
FEATURE_TELEGRAM_FEEDBACK = "telegram.feedback_enabled"

ALL_TELEGRAM_FEATURE_FLAG_KEYS: tuple[str, ...] = (
    FEATURE_TELEGRAM_SUBSCRIPTIONS,
    FEATURE_TELEGRAM_STATISTICS,
    FEATURE_TELEGRAM_NOTIFICATIONS,
    FEATURE_TELEGRAM_AUTHORIZATIONS,
    FEATURE_TELEGRAM_FIXTURES,
    FEATURE_TELEGRAM_SLIPS,
    FEATURE_TELEGRAM_FEEDBACK,
)

_DEFAULT_FEATURE_FLAGS: tuple[dict[str, object], ...] = (
    {
        "key": FEATURE_TELEGRAM_SUBSCRIPTIONS,
        "enabled": True,
        "description": "Mostra comandi e testi abbonamenti nel bot Telegram.",
    },
    {
        "key": FEATURE_TELEGRAM_STATISTICS,
        "enabled": True,
        "description": "Mostra il comando /statistiche nel bot Telegram.",
    },
    {
        "key": FEATURE_TELEGRAM_NOTIFICATIONS,
        "enabled": True,
        "description": "Mostra il comando /notifiche nel bot Telegram.",
    },
    {
        "key": FEATURE_TELEGRAM_AUTHORIZATIONS,
        "enabled": True,
        "description": "Applica il gate whitelist/admin prima dei comandi Telegram.",
    },
    {
        "key": FEATURE_TELEGRAM_FIXTURES,
        "enabled": True,
        "description": "Mostra il comando /partite nel bot Telegram.",
    },
    {
        "key": FEATURE_TELEGRAM_SLIPS,
        "enabled": True,
        "description": "Mostra il comando /schedine nel bot Telegram.",
    },
    {
        "key": FEATURE_TELEGRAM_FEEDBACK,
        "enabled": True,
        "description": "Mostra il comando /feedback nel bot Telegram.",
    },
)


class FeatureFlagError(Exception):
    """Domain error for feature flag operations."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_text(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def _normalize_key(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if not cleaned:
        raise FeatureFlagError("Chiave feature flag obbligatoria.", status_code=400)
    return cleaned[:64]


def _catalog_by_key() -> dict[str, dict[str, object]]:
    return {str(item["key"]): item for item in _DEFAULT_FEATURE_FLAGS}


def _to_read(row: FeatureFlag) -> FeatureFlagRead:
    return FeatureFlagRead(
        key=row.key,
        enabled=bool(row.enabled),
        description=row.description,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def seed_default_feature_flags(db: Session, *, commit: bool = True) -> list[FeatureFlagRead]:
    """Ensure baseline feature flags exist without overriding admin state."""

    now = _utc_now_naive()
    catalog = _catalog_by_key()
    existing = {row.key: row for row in db.scalars(select(FeatureFlag)).all()}
    mutated = False

    for key, definition in catalog.items():
        row = existing.get(key)
        description = _normalize_text(str(definition.get("description") or ""), 255)
        if row is None:
            db.add(
                FeatureFlag(
                    key=key,
                    enabled=bool(definition.get("enabled", True)),
                    description=description,
                    updated_at=now,
                    updated_by="system",
                )
            )
            mutated = True
            continue

        if row.description != description:
            row.description = description
            row.updated_at = now
            mutated = True

    if mutated:
        if commit:
            db.commit()
        else:
            db.flush()

    rows = db.scalars(select(FeatureFlag).order_by(FeatureFlag.key.asc())).all()
    return [_to_read(row) for row in rows]


def list_feature_flags(db: Session) -> list[FeatureFlagRead]:
    seed_default_feature_flags(db, commit=False)
    rows = db.scalars(select(FeatureFlag).order_by(FeatureFlag.key.asc())).all()
    return [_to_read(row) for row in rows]


def set_feature_flag(
    db: Session,
    *,
    key: str,
    enabled: bool,
    updated_by: str | None,
    commit: bool = True,
) -> FeatureFlagRead:
    cleaned_key = _normalize_key(key)
    catalog = _catalog_by_key()
    definition = catalog.get(cleaned_key)
    if definition is None:
        raise FeatureFlagError(f"Feature flag non supportata: {cleaned_key}", status_code=404)

    now = _utc_now_naive()
    row = db.scalar(select(FeatureFlag).where(FeatureFlag.key == cleaned_key))
    description = _normalize_text(str(definition.get("description") or ""), 255)
    if row is None:
        row = FeatureFlag(
            key=cleaned_key,
            enabled=bool(enabled),
            description=description,
            updated_at=now,
            updated_by=_normalize_text(updated_by, 150),
        )
        db.add(row)
    else:
        row.enabled = bool(enabled)
        row.description = description
        row.updated_at = now
        row.updated_by = _normalize_text(updated_by, 150)

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()

    return _to_read(row)


def is_feature_enabled(
    db: Session,
    *,
    key: str,
    default_enabled: bool = True,
) -> bool:
    """Read a flag without mutating state; unknown keys fallback to default."""

    cleaned_key = _normalize_key(key)
    row = db.scalar(select(FeatureFlag).where(FeatureFlag.key == cleaned_key))
    if row is None:
        definition = _catalog_by_key().get(cleaned_key)
        if definition is not None:
            return bool(definition.get("enabled", default_enabled))
        return bool(default_enabled)
    return bool(row.enabled)


def is_feature_enabled_safe(*, key: str, default_enabled: bool = True) -> bool:
    """Safe runtime helper for bot and middleware contexts."""

    try:
        with SessionLocal() as db:
            return is_feature_enabled(db, key=key, default_enabled=default_enabled)
    except Exception:
        logger.exception("Feature flag check failed key=%s", key)
        return bool(default_enabled)


def feature_flag_states(
    db: Session,
    *,
    keys: list[str] | tuple[str, ...],
    default_enabled: bool = True,
) -> dict[str, bool]:
    """Read many feature-flag states in one DB query."""

    normalized: list[str] = [_normalize_key(key) for key in keys]
    if not normalized:
        return {}

    rows = db.scalars(select(FeatureFlag).where(FeatureFlag.key.in_(normalized))).all()
    by_key = {row.key: bool(row.enabled) for row in rows}
    catalog = _catalog_by_key()

    resolved: dict[str, bool] = {}
    for key in normalized:
        if key in by_key:
            resolved[key] = by_key[key]
            continue
        definition = catalog.get(key)
        if definition is not None:
            resolved[key] = bool(definition.get("enabled", default_enabled))
        else:
            resolved[key] = bool(default_enabled)
    return resolved


def feature_flag_states_safe(
    *,
    keys: list[str] | tuple[str, ...],
    default_enabled: bool = True,
) -> dict[str, bool]:
    """Safe helper around ``feature_flag_states`` for runtime handlers."""

    try:
        with SessionLocal() as db:
            return feature_flag_states(
                db,
                keys=keys,
                default_enabled=default_enabled,
            )
    except Exception:
        logger.exception("Feature flag batch check failed keys=%s", ",".join(keys))
        return {(_normalize_key(key)): bool(default_enabled) for key in keys}




