"""Tests for provider-agnostic operational monitoring."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.src.app.observability.alerts import send_admin_alert
from backend.src.app.observability.context import (
    clear_correlation_id,
    ensure_correlation_id,
    get_correlation_id,
)
from backend.src.app.observability.errors import (
    LoggingErrorTracker,
    NullErrorTracker,
    configure_error_tracking,
    get_error_tracker,
)
from backend.src.app.observability.logging import JsonLogFormatter, configure_logging
from backend.src.app.observability.metrics import (
    MetricsRegistry,
    configure_metrics,
    get_metrics,
    record_counter,
)
from backend.src.app.observability.ops_checks import (
    check_import_freshness,
    check_pipeline_duration,
    check_predictions_present,
    run_ops_checks,
)
from backend.src.entity.global_update_run import GlobalUpdateRun
from backend.src.entity.match_prediction import MatchPrediction
from backend.src.utility.sensitive_data import REDACTED
from backend.tests.auth_helpers import (
    auth_header_for_admin,
    create_admin,
    make_test_settings,
    override_settings,
)


def test_correlation_id_roundtrip():
    clear_correlation_id()
    assert get_correlation_id() is None
    cid = ensure_correlation_id("abc-123")
    assert cid == "abc-123"
    assert get_correlation_id() == "abc-123"
    clear_correlation_id()


def test_json_log_includes_correlation_and_redacts_secrets():
    clear_correlation_id()
    ensure_correlation_id("cid-test")
    configure_logging(debug=False, log_format="json", force=True)
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="token=supersecret password=abc",
        args=(),
        exc_info=None,
    )
    # Filters attached to handlers; apply formatter after manual filter fields.
    from backend.src.app.observability.logging import CorrelationIdFilter, SensitiveDataFilter

    SensitiveDataFilter().filter(record)
    CorrelationIdFilter().filter(record)
    line = JsonLogFormatter().format(record)
    payload = json.loads(line)
    assert payload["correlation_id"] == "cid-test"
    assert "supersecret" not in line
    assert REDACTED in line
    clear_correlation_id()


def test_metrics_registry_prometheus_render():
    registry = MetricsRegistry()
    registry.incr("http_requests_total", labels={"method": "GET", "status": "200", "path": "/api/x"})
    registry.observe("http_request_duration_seconds", 0.12, labels={"method": "GET", "status": "200", "path": "/api/x"})
    text = registry.render_prometheus()
    assert "http_requests_total{" in text
    assert "http_request_duration_seconds_count" in text
    assert "process_uptime_seconds" in text


def test_metrics_endpoint_and_correlation_headers(client):
    configure_metrics("memory")
    record_counter("test_probe_total", labels={"k": "v"})
    response = client.get("/health", headers={"X-Correlation-ID": "req-fixed-1"})
    assert response.status_code == 200
    assert response.headers.get("X-Correlation-ID") == "req-fixed-1"
    assert response.headers.get("X-Request-ID") == "req-fixed-1"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "text/plain" in metrics.headers.get("content-type", "")
    assert "process_uptime_seconds" in metrics.text

    deps = client.get("/deps")
    assert deps.status_code == 200
    body = deps.json()
    assert body["status"] == "ok"
    assert "database" in body["dependencies"]


def test_metrics_disabled_returns_404(client):
    settings = make_test_settings(metrics_endpoint_enabled=False, metrics_provider="none")
    override_settings(settings)
    configure_metrics("none")
    try:
        response = client.get("/metrics")
        assert response.status_code == 404
    finally:
        configure_metrics("memory")


def test_error_tracking_providers():
    configure_error_tracking(provider="none")
    assert isinstance(get_error_tracker(), NullErrorTracker)
    configure_error_tracking(provider="logging")
    assert isinstance(get_error_tracker(), LoggingErrorTracker)
    configure_error_tracking(provider="webhook", webhook_url="")
    # empty webhook falls back to logging
    assert isinstance(get_error_tracker(), LoggingErrorTracker)


@patch("backend.src.app.observability.alerts.httpx.post")
def test_admin_alert_telegram(mock_post):
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_post.return_value = mock_response
    result = send_admin_alert(
        "pipeline failed",
        severity="critical",
        dedupe_key=None,
        telegram_bot_token="fake-token",
        telegram_admin_chat_id="12345",
        enabled=True,
        cooldown_seconds=0,
    )
    assert result["sent"] is True
    assert result["telegram"] == "ok"
    assert mock_post.called
    # Token must not appear in logged kwargs beyond URL construction; URL contains token by Bot API design.
    call_json = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
    assert "pipeline failed" in call_json["text"]


def test_ops_checks_with_data(db_session: Session):
    now = datetime.now()
    db_session.add(
        MatchPrediction(
            event_key=1001,
            model_version="v3",
            model_name="logistic_regression",
            predicted_at=now,
            predicted_winner="A",
        )
    )
    db_session.add(
        GlobalUpdateRun(
            run_date=date.today(),
            origin="job",
            status="completed",
            force="false",
            cancel_requested="false",
            resume_count=0,
            sync_cloud="false",
            versions_processed=1,
            models_processed=1,
            combinations_completed=1,
            combinations_failed=0,
            combinations_skipped=0,
            fixtures_processed=1,
            slips_generated=0,
            duration_seconds=120.0,
            created_at=now,
            started_at=now - timedelta(minutes=2),
            finished_at=now,
        )
    )
    db_session.commit()

    with patch(
        "backend.src.app.observability.ops_checks.get_import_status",
        return_value={
            "next_fixtures_imported_today": True,
            "next_fixtures_last_imported_at": now,
            "fixtures_last_imported_at": now,
        },
    ):
        report = run_ops_checks(
            db_session,
            import_max_age_hours=36,
            predictions_lookback_hours=36,
            max_duration_seconds=7200,
        )
    assert report["status"] == "ok"
    names = {c["name"] for c in report["checks"]}
    assert names == {
        "import_freshness",
        "predictions_present",
        "pipeline_duration",
        "latest_run_outcome",
    }


def test_ops_checks_detect_stale_import_and_missing_predictions(db_session: Session):
    stale = datetime.now() - timedelta(hours=72)
    with patch(
        "backend.src.app.observability.ops_checks.get_import_status",
        return_value={
            "next_fixtures_imported_today": False,
            "next_fixtures_last_imported_at": stale,
            "fixtures_last_imported_at": stale,
        },
    ):
        import_check = check_import_freshness(db_session, max_age_hours=36)
        pred_check = check_predictions_present(db_session, lookback_hours=36)
    assert import_check.status in ("warning", "critical")
    assert pred_check.status == "critical"


def test_pipeline_duration_anomaly(db_session: Session):
    now = datetime.now()
    db_session.add(
        GlobalUpdateRun(
            run_date=date.today(),
            origin="job",
            status="completed",
            force="false",
            cancel_requested="false",
            resume_count=0,
            sync_cloud="false",
            versions_processed=1,
            models_processed=1,
            combinations_completed=1,
            combinations_failed=0,
            combinations_skipped=0,
            fixtures_processed=1,
            slips_generated=0,
            duration_seconds=99999.0,
            created_at=now,
            started_at=now,
            finished_at=now,
        )
    )
    db_session.commit()
    check = check_pipeline_duration(db_session, max_duration_seconds=7200)
    assert check.status == "warning"


def test_ops_checks_endpoint_requires_admin(client, db_session: Session):
    denied = client.get("/api/ops/checks")
    assert denied.status_code in (401, 403)
    admin = create_admin(db_session)
    settings = make_test_settings()
    override_settings(settings)
    ok = client.get("/api/ops/checks", headers=auth_header_for_admin(admin, settings))
    assert ok.status_code == 200
    assert "checks" in ok.json()


def test_deps_excluded_from_rate_limit():
    from backend.src.app.middleware.rate_limit import is_excluded_path

    assert is_excluded_path("/deps")
    assert is_excluded_path("/metrics")
    assert is_excluded_path("/metrics.json")
