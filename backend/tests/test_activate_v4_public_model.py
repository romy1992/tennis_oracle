"""Tests for the Fase 6 v4 public registry activation script (ML-07)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.src.app.ml.training.activate_v4_public_model import MODEL_NAME, MODEL_VERSION, activate_v4
from backend.src.app.schemas.public_model_registry import PublicModelRegistryArtifacts


def _artifacts(*, exists: bool = True) -> PublicModelRegistryArtifacts:
    return PublicModelRegistryArtifacts(
        model_pkl="/models/v4/voting_ensemble.pkl",
        metrics_path="/reports/baseline_v4_metrics.json",
        model_exists=exists,
        metrics_exists=exists,
    )


@patch("backend.src.app.services.public_model_registry.resolve_model_artifacts")
@patch("backend.src.app.services.public_model_registry.load_holdout_approval_metrics")
def test_dry_run_registers_candidate_without_activating(mock_metrics, mock_artifacts, db_session):
    mock_artifacts.return_value = _artifacts()
    mock_metrics.return_value = {"source": "holdout", "available": True}

    result = activate_v4(dry_run=True, db=db_session)

    assert result["action"] == "registered_only"
    assert result["candidate"]["model_version"] == MODEL_VERSION
    assert result["candidate"]["model_name"] == MODEL_NAME
    assert result["candidate"]["status"] == "candidate"


@patch("backend.src.app.services.public_model_registry.resolve_model_artifacts")
@patch("backend.src.app.services.public_model_registry.load_holdout_approval_metrics")
def test_activates_v4_and_retires_previous_active(mock_metrics, mock_artifacts, db_session):
    from datetime import datetime, timezone

    from backend.src.entity.public_model_registry import PublicModelRegistryEntry

    mock_artifacts.return_value = _artifacts()
    mock_metrics.return_value = {"source": "holdout", "available": True}

    # Simula un modello v3 precedentemente attivo.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    previous = PublicModelRegistryEntry(
        model_version="v3",
        model_name="logistic_regression",
        status="active",
        activated_at=now,
        approval_metrics_json='{"source":"test"}',
        artifacts_json=_artifacts().model_dump_json(),
        motivation="pre-esistente",
        created_at=now,
        created_by="test",
        updated_at=now,
    )
    db_session.add(previous)
    db_session.commit()

    result = activate_v4(db=db_session)

    assert result["action"] == "activated"
    assert result["active"]["model_version"] == MODEL_VERSION
    assert result["active"]["model_name"] == MODEL_NAME
    assert result["active"]["status"] == "active"
    assert result["previous_active"]["model_version"] == "v3"
    assert result["previous_active"]["status"] == "retired"


if __name__ == "__main__":
    pytest.main([__file__])

