"""Tests for ML-07 public model registry."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.src.app.schemas.public_model_registry import PublicModelRegistryArtifacts
from backend.src.app.services.live_publication_service import resolve_public_model_config
from backend.src.app.services.public_model_registry import (
    activate_registry_entry,
    register_candidate,
    rollback_active_registry_entry,
)
from backend.src.entity.public_model_registry import PublicModelRegistryEntry
from backend.tests.auth_helpers import make_test_settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _artifacts(*, exists: bool = True) -> PublicModelRegistryArtifacts:
    return PublicModelRegistryArtifacts(
        model_pkl="/models/v3/logistic_regression.pkl",
        metrics_path="/reports/baseline_v3_metrics.json",
        model_exists=exists,
        metrics_exists=exists,
    )


def _seed_active(db_session, *, model_version: str = "v3", model_name: str = "logistic_regression"):
    now = _utc_now()
    artifacts = _artifacts()
    row = PublicModelRegistryEntry(
        model_version=model_version,
        model_name=model_name,
        status="active",
        activated_at=now,
        approval_metrics_json='{"source":"test"}',
        artifacts_json=artifacts.model_dump_json(),
        motivation="test active",
        created_at=now,
        created_by="test",
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@patch("backend.src.app.services.public_model_registry.resolve_model_artifacts")
def test_register_candidate_requires_artifacts(mock_resolve, db_session):
    mock_resolve.return_value = _artifacts(exists=False)

    with pytest.raises(ValueError, match="Artefatto modello mancante"):
        register_candidate(
            db_session,
            model_version="v4",
            model_name="logistic_regression",
            motivation="candidate test",
        )


@patch("backend.src.app.services.public_model_registry.resolve_model_artifacts")
@patch("backend.src.app.services.public_model_registry.load_holdout_approval_metrics")
def test_activate_and_rollback_lifecycle(mock_metrics, mock_artifacts, db_session):
    mock_artifacts.return_value = _artifacts()
    mock_metrics.return_value = {"source": "holdout", "available": True}

    first = register_candidate(
        db_session,
        model_version="v4",
        model_name="logistic_regression",
        motivation="first candidate",
    )
    active_a, _ = activate_registry_entry(
        db_session,
        first.id,
        motivation="go live v4/lr",
    )
    assert active_a.status == "active"
    assert active_a.activated_at is not None

    second = register_candidate(
        db_session,
        model_version="v4",
        model_name="random_forest",
        motivation="rf candidate",
    )
    active_b, retired_a = activate_registry_entry(
        db_session,
        second.id,
        motivation="switch to rf",
    )
    assert active_b.status == "active"
    assert retired_a is not None
    assert retired_a.status == "retired"
    assert active_b.supersedes_entry_id == retired_a.id

    restored, retired_b = rollback_active_registry_entry(
        db_session,
        motivation="rf underperformed",
    )
    assert restored.model_name == "logistic_regression"
    assert restored.status == "active"
    assert retired_b.status == "retired"


def test_resolve_public_model_config_prefers_registry(db_session):
    _seed_active(db_session, model_version="v4", model_name="voting_ensemble")
    cfg = resolve_public_model_config(
        make_test_settings(
            live_publication_enabled=True,
            public_model_version="v2",
            public_model_name="random_forest",
        ),
        db=db_session,
    )
    assert cfg.status == "ready"
    assert cfg.model_version == "v4"
    assert cfg.model_name == "voting_ensemble"
    assert cfg.source == "registry"


def test_resolve_public_model_config_env_fallback(db_session):
    cfg = resolve_public_model_config(
        make_test_settings(
            live_publication_enabled=True,
            public_model_version="v4",
            public_model_name="logistic_regression",
        ),
        db=db_session,
    )
    assert cfg.status == "ready"
    assert cfg.source == "env"
    assert cfg.model_version == "v4"


def test_public_model_registry_api(client, auth_headers, db_session, tmp_path: Path):
    artifacts = PublicModelRegistryArtifacts(
        model_pkl=str(tmp_path / "model.pkl"),
        metrics_path=str(tmp_path / "metrics.json"),
        model_exists=True,
        metrics_exists=True,
    )
    (tmp_path / "model.pkl").write_text("fake", encoding="utf-8")

    with patch(
        "backend.src.app.services.public_model_registry.resolve_model_artifacts",
        return_value=artifacts,
    ), patch(
        "backend.src.app.services.public_model_registry.load_holdout_approval_metrics",
        return_value={"source": "holdout"},
    ):
        create_resp = client.post(
            "/api/public-model-registry/candidates",
            json={
                "model_version": "v4",
                "model_name": "logistic_regression",
                "motivation": "api candidate",
            },
            headers=auth_headers,
        )
    assert create_resp.status_code == 201
    entry_id = create_resp.json()["id"]

    activate_resp = client.post(
        f"/api/public-model-registry/entries/{entry_id}/activate",
        json={"motivation": "approved for live"},
        headers=auth_headers,
    )
    assert activate_resp.status_code == 200
    assert activate_resp.json()["entry"]["status"] == "active"

    active_resp = client.get("/api/public-model-registry/active")
    assert active_resp.status_code == 200
    assert active_resp.json()["model_version"] == "v4"

    list_resp = client.get("/api/public-model-registry", headers=auth_headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["active"]["id"] == entry_id
