"""Database-backed runtime settings and API-Tennis credential resolution."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.entity.runtime_secret import RuntimeSecret

logger = logging.getLogger(__name__)

API_TENNIS_SECRET_KEY = "provider.api_tennis.key"
FERNET_SCHEME = "fernet-v1"
DATABASE_VALUE_SCHEME = "database-v1"


class RuntimeSecretError(RuntimeError):
    """Safe domain error for runtime-setting operations."""


class RuntimeSecretStorageNotConfigured(RuntimeSecretError):
    """The environment wrapping key is missing or invalid."""


class RuntimeSecretDecryptionError(RuntimeSecretError):
    """A stored secret cannot be decrypted with the configured wrapping key."""


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _secret_text(value: SecretStr | str | None) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value().strip()
    return (value or "").strip()


def secret_fingerprint(value: str) -> str:
    """Return a short, non-reversible identifier safe for status/audit output."""

    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()[:12]}"


def _fernet(settings: Settings) -> Fernet:
    raw_key = _secret_text(settings.runtime_secrets_master_key)
    if not raw_key:
        raise RuntimeSecretStorageNotConfigured(
            "RUNTIME_SECRETS_MASTER_KEY non configurata per questo ambiente."
        )
    try:
        return Fernet(raw_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeSecretStorageNotConfigured(
            "RUNTIME_SECRETS_MASTER_KEY non è una chiave Fernet valida."
        ) from exc


def runtime_secret_storage_ready(settings: Settings) -> bool:
    """Return whether the dashboard can save settings.

    New values are stored directly in the protected application database, so
    saving does not require an additional deployment secret. The settings
    argument remains for API compatibility with older callers.
    """

    _ = settings
    return True


def get_runtime_secret_row(db: Session, *, key: str) -> RuntimeSecret | None:
    return db.scalar(select(RuntimeSecret).where(RuntimeSecret.key == key))


def decrypt_runtime_secret(row: RuntimeSecret, *, settings: Settings) -> str:
    if row.encryption_scheme == DATABASE_VALUE_SCHEME:
        return row.encrypted_value
    if row.encryption_scheme != FERNET_SCHEME:
        raise RuntimeSecretDecryptionError(
            f"Schema di cifratura non supportato: {row.encryption_scheme}."
        )
    try:
        plaintext = _fernet(settings).decrypt(row.encrypted_value.encode("ascii"))
        return plaintext.decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise RuntimeSecretDecryptionError(
            "Il segreto salvato non può essere decifrato in questo ambiente."
        ) from exc


def set_runtime_secret(
    db: Session,
    *,
    settings: Settings,
    key: str,
    value: str,
    updated_by: str,
) -> RuntimeSecret:
    cleaned = value.strip()
    if len(cleaned) < 8 or len(cleaned) > 512:
        raise RuntimeSecretError("La chiave deve contenere tra 8 e 512 caratteri.")

    now = _utc_now_naive()
    _ = settings
    stored_value = cleaned
    row = get_runtime_secret_row(db, key=key)
    if row is None:
        row = RuntimeSecret(
            key=key,
            encrypted_value=stored_value,
            encryption_scheme=DATABASE_VALUE_SCHEME,
            fingerprint=secret_fingerprint(cleaned),
            created_at=now,
            updated_at=now,
            updated_by=updated_by[:150],
        )
        db.add(row)
    else:
        row.encrypted_value = stored_value
        row.encryption_scheme = DATABASE_VALUE_SCHEME
        row.fingerprint = secret_fingerprint(cleaned)
        row.updated_at = now
        row.updated_by = updated_by[:150]
    db.flush()
    return row


def environment_api_tennis_key(settings: Settings) -> str | None:
    value = _secret_text(settings.api_tennis_key)
    return value or None


def resolve_api_tennis_key_from_db(
    db: Session,
    *,
    settings: Settings,
    environment_fallback: str | None = None,
) -> str | None:
    """Resolve DB override first, then the environment bootstrap value."""

    row = get_runtime_secret_row(db, key=API_TENNIS_SECRET_KEY)
    if row is not None:
        return decrypt_runtime_secret(row, settings=settings)
    return environment_fallback or environment_api_tennis_key(settings)


def resolve_api_tennis_key(*, environment_fallback: str | None = None) -> str | None:
    """Resolve the active key for workers that do not own a request DB session.

    During a migration rollout, a missing table falls back to the environment
    key. A present but unreadable DB override fails closed rather than silently
    using an older credential.
    """

    settings = get_settings()
    fallback = environment_fallback or environment_api_tennis_key(settings)
    # Import the module rather than SessionLocal directly: tests and local tools
    # can safely rebind the canonical session factory.
    from backend.src.app.db import session as db_session_module

    try:
        with db_session_module.SessionLocal() as db:
            return resolve_api_tennis_key_from_db(
                db,
                settings=settings,
                environment_fallback=fallback,
            )
    except RuntimeSecretDecryptionError:
        raise
    except SQLAlchemyError:
        logger.warning(
            "Runtime-secret storage unavailable; using API-Tennis environment fallback.",
            exc_info=True,
        )
        return fallback


def api_tennis_secret_status(db: Session, *, settings: Settings) -> dict[str, object]:
    """Return provider status metadata without ever returning secret material."""

    row = get_runtime_secret_row(db, key=API_TENNIS_SECRET_KEY)
    environment_key = environment_api_tennis_key(settings)
    storage_ready = runtime_secret_storage_ready(settings)
    warning: str | None = None
    usable = False
    source = "missing"
    fingerprint: str | None = None
    updated_at = None
    updated_by = None

    if row is not None:
        source = "database"
        fingerprint = row.fingerprint
        updated_at = row.updated_at
        updated_by = row.updated_by
        try:
            usable = bool(decrypt_runtime_secret(row, settings=settings))
        except RuntimeSecretDecryptionError as exc:
            warning = str(exc)
    elif environment_key:
        source = "environment"
        fingerprint = secret_fingerprint(environment_key)
        usable = True

    return {
        "configured": source != "missing",
        "usable": usable,
        "source": source,
        "fingerprint": fingerprint,
        "storage_ready": storage_ready,
        "database_override_present": row is not None,
        "updated_at": updated_at,
        "updated_by": updated_by,
        "warning": warning,
    }
