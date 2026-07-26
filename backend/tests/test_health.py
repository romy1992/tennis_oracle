"""Health and readiness endpoint tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.src.app.middleware.rate_limit import is_excluded_path


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "environment" in body
    assert "debug" in body


def test_ready_ok_when_db_reachable(client):
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"
    assert "environment" in body


def test_ready_503_when_db_fails(client):
    mock_session = MagicMock()
    mock_session.__enter__.return_value = mock_session
    mock_session.__exit__.return_value = False
    mock_session.execute.side_effect = RuntimeError("db down")

    with patch(
        "backend.src.app.api.routes.health.SessionLocal",
        return_value=mock_session,
    ):
        response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "error"


def test_ready_excluded_from_rate_limit():
    assert is_excluded_path("/ready")
    assert is_excluded_path("/ready/")
    assert is_excluded_path("/health")
    assert is_excluded_path("/deps")
    assert is_excluded_path("/metrics")


def test_deps_ok(client):
    response = client.get("/deps")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["database"]["status"] == "ok"
    assert "error_tracking" in body["dependencies"]
