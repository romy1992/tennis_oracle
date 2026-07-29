"""Official public model registry service (ML-07).

Manages candidate / active / retired lifecycle for the single public model
used by live publication and the Telegram bot. Does not alter historical
``PublishedPrediction`` rows when the active model changes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.src.app.ml.model_selection import _read_metrics
from backend.src.app.ml.model_versioning import MODEL_VERSIONS, REPORTS_DIR, ModelVersion
from backend.src.app.schemas.public_model_registry import (
    PublicModelRegistryArtifacts,
    PublicModelRegistryEntryRead,
)
from backend.src.entity.public_model_registry import PublicModelRegistryEntry

logger = logging.getLogger(__name__)

ALLOWED_PUBLIC_MODEL_VERSIONS = frozenset({"v1", "v2", "v3"})
ALLOWED_PUBLIC_MODEL_NAMES = frozenset({"logistic_regression", "random_forest"})
OPEN_STATUSES = frozenset({"candidate", "active"})
PublicModelRegistryStatus = Literal["candidate", "active", "retired"]


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _validate_combo(model_version: str, model_name: str) -> None:
    if model_version not in ALLOWED_PUBLIC_MODEL_VERSIONS:
        allowed = ", ".join(sorted(ALLOWED_PUBLIC_MODEL_VERSIONS))
        raise ValueError(f"model_version non valida: {model_version}. Consentite: {allowed}")
    if model_name not in ALLOWED_PUBLIC_MODEL_NAMES:
        allowed = ", ".join(sorted(ALLOWED_PUBLIC_MODEL_NAMES))
        raise ValueError(f"model_name non valido: {model_name}. Consentiti: {allowed}")


def resolve_model_artifacts(
    model_version: str,
    model_name: str,
    *,
    walk_forward_run_id: int | None = None,
    calibration_run_id: int | None = None,
    calibration_artifacts: dict[str, str] | None = None,
) -> PublicModelRegistryArtifacts:
    """Resolve on-disk artifact paths for a version/estimator pair."""
    _validate_combo(model_version, model_name)
    paths = MODEL_VERSIONS[model_version]  # type: ignore[index]
    model_pkl = paths.models_dir / f"{model_name}.pkl"
    metrics_path = REPORTS_DIR / paths.metrics_filename
    return PublicModelRegistryArtifacts(
        model_pkl=str(model_pkl),
        metrics_path=str(metrics_path),
        model_exists=model_pkl.is_file(),
        metrics_exists=metrics_path.is_file(),
        walk_forward_run_id=walk_forward_run_id,
        calibration_run_id=calibration_run_id,
        calibration_artifacts=dict(calibration_artifacts or {}),
    )


def load_holdout_approval_metrics(model_version: str, model_name: str) -> dict[str, Any]:
    """Load holdout metrics for one estimator from the version metrics JSON."""
    _validate_combo(model_version, model_name)
    paths = MODEL_VERSIONS[model_version]  # type: ignore[index]
    metrics_path = REPORTS_DIR / paths.metrics_filename
    if not metrics_path.is_file():
        return {"source": "holdout", "metrics_path": str(metrics_path), "available": False}

    payload = _read_metrics(metrics_path)
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    model_metrics = models.get(model_name)
    if not isinstance(model_metrics, dict):
        comparison = payload.get("comparison")
        if isinstance(comparison, list):
            for item in comparison:
                if isinstance(item, dict) and item.get("model") == model_name:
                    model_metrics = item
                    break
    return {
        "source": "holdout",
        "metrics_path": str(metrics_path),
        "available": isinstance(model_metrics, dict),
        "model_metrics": model_metrics if isinstance(model_metrics, dict) else None,
        "split": payload.get("split"),
    }


def _entry_to_read(row: PublicModelRegistryEntry) -> PublicModelRegistryEntryRead:
    artifacts_raw = _json_loads(row.artifacts_json, {})
    artifacts = PublicModelRegistryArtifacts.model_validate(artifacts_raw)
    return PublicModelRegistryEntryRead(
        id=row.id,
        model_version=row.model_version,
        model_name=row.model_name,
        status=row.status,  # type: ignore[arg-type]
        activated_at=row.activated_at,
        retired_at=row.retired_at,
        approval_metrics=_json_loads(row.approval_metrics_json, {}),
        motivation=row.motivation,
        artifacts=artifacts,
        supersedes_entry_id=row.supersedes_entry_id,
        walk_forward_run_id=row.walk_forward_run_id,
        calibration_run_id=row.calibration_run_id,
        created_at=row.created_at,
        created_by=row.created_by,
        updated_at=row.updated_at,
    )


def get_active_registry_entry(db: Session) -> PublicModelRegistryEntry | None:
    return db.scalar(
        select(PublicModelRegistryEntry)
        .where(PublicModelRegistryEntry.status == "active")
        .order_by(PublicModelRegistryEntry.activated_at.desc(), PublicModelRegistryEntry.id.desc())
        .limit(1)
    )


def get_registry_entry(db: Session, entry_id: int) -> PublicModelRegistryEntry | None:
    return db.get(PublicModelRegistryEntry, entry_id)


def list_registry_entries(
    db: Session,
    *,
    status: PublicModelRegistryStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PublicModelRegistryEntry], int]:
    stmt = select(PublicModelRegistryEntry)
    count_stmt = select(func.count()).select_from(PublicModelRegistryEntry)
    if status is not None:
        stmt = stmt.where(PublicModelRegistryEntry.status == status)
        count_stmt = count_stmt.where(PublicModelRegistryEntry.status == status)
    total = int(db.scalar(count_stmt) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(
                PublicModelRegistryEntry.created_at.desc(),
                PublicModelRegistryEntry.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, total


def _assert_artifacts_available(artifacts: PublicModelRegistryArtifacts) -> None:
    if not artifacts.model_exists:
        raise ValueError(
            f"Artefatto modello mancante: {artifacts.model_pkl}. "
            "Addestra o monta il file .pkl prima di registrare il candidato."
        )


def register_candidate(
    db: Session,
    *,
    model_version: str,
    model_name: str,
    motivation: str | None = None,
    approval_metrics: dict[str, Any] | None = None,
    walk_forward_run_id: int | None = None,
    calibration_run_id: int | None = None,
    created_by: str = "admin_api",
) -> PublicModelRegistryEntry:
    """Register a new candidate public model (does not activate)."""
    _validate_combo(model_version, model_name)
    existing = db.scalar(
        select(PublicModelRegistryEntry)
        .where(
            PublicModelRegistryEntry.model_version == model_version,
            PublicModelRegistryEntry.model_name == model_name,
            PublicModelRegistryEntry.status.in_(tuple(OPEN_STATUSES)),
        )
        .limit(1)
    )
    if existing is not None:
        raise ValueError(
            f"Esiste già una voce {existing.status} per {model_version}/{model_name} "
            f"(id={existing.id})."
        )

    artifacts = resolve_model_artifacts(
        model_version,
        model_name,
        walk_forward_run_id=walk_forward_run_id,
        calibration_run_id=calibration_run_id,
    )
    _assert_artifacts_available(artifacts)

    metrics_payload = approval_metrics or load_holdout_approval_metrics(model_version, model_name)
    now = _utc_now_naive()
    row = PublicModelRegistryEntry(
        model_version=model_version,
        model_name=model_name,
        status="candidate",
        approval_metrics_json=_json_dumps(metrics_payload),
        motivation=motivation,
        artifacts_json=_json_dumps(artifacts.model_dump(mode="json")),
        walk_forward_run_id=walk_forward_run_id,
        calibration_run_id=calibration_run_id,
        created_at=now,
        created_by=created_by,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def activate_registry_entry(
    db: Session,
    entry_id: int,
    *,
    motivation: str,
    created_by: str = "admin_api",
) -> tuple[PublicModelRegistryEntry, PublicModelRegistryEntry | None]:
    """Promote a candidate to active; retire the previous active entry."""
    entry = get_registry_entry(db, entry_id)
    if entry is None:
        raise ValueError(f"Voce registro {entry_id} non trovata")
    if entry.status != "candidate":
        raise ValueError(f"Solo i candidati possono essere attivati (stato attuale: {entry.status})")

    artifacts = PublicModelRegistryArtifacts.model_validate(
        _json_loads(entry.artifacts_json, {})
    )
    _assert_artifacts_available(artifacts)

    previous_active = get_active_registry_entry(db)
    now = _utc_now_naive()

    if previous_active is not None:
        if previous_active.id == entry.id:
            raise ValueError("La voce è già attiva")
        previous_active.status = "retired"
        previous_active.retired_at = now
        previous_active.updated_at = now

    entry.status = "active"
    entry.activated_at = now
    entry.retired_at = None
    entry.motivation = motivation
    entry.supersedes_entry_id = previous_active.id if previous_active is not None else None
    entry.updated_at = now

    db.commit()
    db.refresh(entry)
    if previous_active is not None:
        db.refresh(previous_active)
    logger.info(
        "Public model activated id=%s %s/%s (supersedes=%s)",
        entry.id,
        entry.model_version,
        entry.model_name,
        entry.supersedes_entry_id,
    )
    return entry, previous_active


def rollback_active_registry_entry(
    db: Session,
    *,
    motivation: str,
    created_by: str = "admin_api",
) -> tuple[PublicModelRegistryEntry, PublicModelRegistryEntry]:
    """Reactivate the entry superseded by the current active model."""
    current = get_active_registry_entry(db)
    if current is None:
        raise ValueError("Nessun modello pubblico attivo da ripristinare")
    if current.supersedes_entry_id is None:
        raise ValueError(
            "Il modello attivo non ha un predecessore registrato; rollback non disponibile"
        )

    previous = get_registry_entry(db, current.supersedes_entry_id)
    if previous is None:
        raise ValueError(f"Predecessore id={current.supersedes_entry_id} non trovato")
    if previous.status != "retired":
        raise ValueError(
            f"Predecessore id={previous.id} non è retired (stato={previous.status})"
        )

    artifacts = PublicModelRegistryArtifacts.model_validate(
        _json_loads(previous.artifacts_json, {})
    )
    _assert_artifacts_available(artifacts)

    now = _utc_now_naive()
    current.status = "retired"
    current.retired_at = now
    current.updated_at = now

    previous.status = "active"
    previous.activated_at = now
    previous.retired_at = None
    previous.motivation = f"Rollback: {motivation}"
    previous.supersedes_entry_id = current.id
    previous.updated_at = now

    db.commit()
    db.refresh(previous)
    db.refresh(current)
    logger.info(
        "Public model rollback to id=%s %s/%s (from id=%s)",
        previous.id,
        previous.model_version,
        previous.model_name,
        current.id,
    )
    return previous, current


def resolve_public_model_from_registry(
    db: Session | None,
) -> tuple[str, str] | None:
    """Return (model_version, model_name) from the active registry entry, if any."""
    if db is None:
        return None
    active = get_active_registry_entry(db)
    if active is None:
        return None
    return active.model_version, active.model_name


def entry_to_read(row: PublicModelRegistryEntry) -> PublicModelRegistryEntryRead:
    return _entry_to_read(row)
