"""Scheduled daily/weekly cascade, provenance, dedupe, and Resend tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.src.app.observability.email_reports import EmailAttachment, send_report_email
from backend.src.app.services.scheduled_reports import (
    JobSource,
    calibration_model_error_lines,
    list_stale_daily_report_dates,
    run_daily_scheduled_report,
    run_weekly_scheduled_report,
)
from backend.src.jobs.run_report_scheduler import run_due
from backend.src.entity.calibration import CalibrationRun
from backend.src.entity.global_update_run import GlobalUpdateRun
from backend.src.entity.scheduled_report_job import ScheduledReportJob
from backend.src.entity.walk_forward import WalkForwardRun
from backend.tests.auth_helpers import make_test_settings


SCHEDULE_DATE = date(2026, 8, 31)  # Monday
SOURCE = JobSource(
    environment="test",
    name="test-worker",
    url="https://dev.example.test",
    hostname="test-host",
    path="/srv/tennis_oracle",
)


def _global_run(db: Session, *, status: str = "completed") -> GlobalUpdateRun:
    now = datetime(2026, 8, 31, 6, 0, 0)
    run = GlobalUpdateRun(
        run_date=SCHEDULE_DATE,
        origin="job",
        status=status,
        force="false",
        created_at=now,
        started_at=now,
        finished_at=now,
        duration_seconds=12.5,
        report_json='{"ok": true}',
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _walk_forward_run(db: Session, *, status: str = "completed") -> WalkForwardRun:
    now = datetime(2026, 8, 31, 8, 0, 0)
    run = WalkForwardRun(
        status=status,
        mode="expanding",
        initial_train_days=365,
        test_days=90,
        step_days=90,
        min_train_rows=200,
        min_test_rows=50,
        embargo_days=0,
        edge_threshold=0.03,
        random_state=42,
        versions_requested="v4,first_set_winner_v2,over_under_games_v1",
        origin="job",
        cancel_requested="false",
        created_at=now,
        started_at=now,
        finished_at=now,
        duration_seconds=30.0,
        summary_json='{"folds_errors": 0}',
        created_by="test",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _calibration_run(
    db: Session,
    *,
    walk_forward_run_id: int,
    status: str = "completed",
) -> CalibrationRun:
    now = datetime(2026, 8, 31, 8, 30, 0)
    run = CalibrationRun(
        status=status,
        walk_forward_run_id=walk_forward_run_id,
        n_bins=10,
        min_bin_samples=30,
        min_calibrator_train_samples=100,
        wf_mode="expanding",
        wf_initial_train_days=365,
        wf_test_days=90,
        wf_step_days=90,
        wf_min_train_rows=200,
        wf_min_test_rows=50,
        wf_embargo_days=0,
        wf_edge_threshold=0.03,
        wf_random_state=42,
        methods_requested="raw,platt,isotonic",
        versions_requested="v4,first_set_winner_v2,over_under_games_v1",
        origin="job",
        cancel_requested="false",
        created_at=now,
        started_at=now,
        finished_at=now,
        duration_seconds=20.0,
        summary_json='{"models_with_oos": 3}',
        created_by="test",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _settings(**overrides):
    values = {
        "app_env": "test",
        "scheduled_reports_timezone": "Europe/Rome",
        "scheduled_global_update_time": "08:00",
        "scheduled_weekly_validation_day": 0,
        "scheduled_weekly_validation_time": "10:00",
        "scheduled_reports_enabled": True,
        "report_email_enabled": False,
    }
    values.update(overrides)
    return make_test_settings(**values)


def test_daily_job_records_source_and_deduplicates(db_session: Session) -> None:
    calls = 0

    def start(db: Session, **_kwargs):
        nonlocal calls
        calls += 1
        return _global_run(db), "ok"

    first, first_claimed = run_daily_scheduled_report(
        db_session,
        _settings(),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        global_update_starter=start,
    )
    second, second_claimed = run_daily_scheduled_report(
        db_session,
        _settings(),
        scheduled_date=SCHEDULE_DATE,
        source=JobSource("other", "other", None, "other", "/other"),
        global_update_starter=start,
    )

    assert first_claimed is True
    assert second_claimed is False
    assert calls == 1
    assert second.id == first.id
    assert first.status == "completed"
    assert first.email_status == "disabled"
    assert first.source_environment == "test"
    assert first.source_url == "https://dev.example.test"
    assert first.source_path == "/srv/tennis_oracle"


def test_daily_job_recovers_stale_report_after_terminal_global_update(
    db_session: Session,
) -> None:
    completed = _global_run(db_session)
    stale_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    stuck = ScheduledReportJob(
        schedule_key=f"daily_global_update:{SCHEDULE_DATE.isoformat()}",
        job_name="daily_global_update",
        scheduled_for=datetime(2026, 8, 31, 6, 0, 0),
        status="running",
        source_environment="test",
        source_name="dead-worker",
        source_url=None,
        source_hostname="dead-host",
        source_path="/old",
        started_at=stale_at,
        created_at=stale_at,
        updated_at=stale_at,
    )
    db_session.add(stuck)
    db_session.commit()
    stuck_id = stuck.id
    starter = MagicMock(return_value=(None, "already completed"))

    recovered, claimed = run_daily_scheduled_report(
        db_session,
        _settings(scheduled_reports_recovery_seconds=60),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        global_update_starter=starter,
    )

    assert claimed is True
    assert recovered.id == stuck_id
    assert recovered.status == "completed"
    assert recovered.global_update_run_id == completed.id
    assert recovered.email_status == "disabled"
    assert recovered.source_name == SOURCE.name
    assert "recovered stale" in (recovered.message or "").lower()
    starter.assert_not_called()


def test_daily_job_does_not_recover_recent_running_report(db_session: Session) -> None:
    _global_run(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stuck = ScheduledReportJob(
        schedule_key=f"daily_global_update:{SCHEDULE_DATE.isoformat()}",
        job_name="daily_global_update",
        scheduled_for=datetime(2026, 8, 31, 6, 0, 0),
        status="running",
        source_environment="test",
        source_name="active-worker",
        source_url=None,
        source_hostname="active-host",
        source_path="/active",
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(stuck)
    db_session.commit()
    starter = MagicMock()

    current, claimed = run_daily_scheduled_report(
        db_session,
        _settings(scheduled_reports_recovery_seconds=3600),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        global_update_starter=starter,
    )

    assert claimed is False
    assert current.status == "running"
    starter.assert_not_called()


def test_stale_daily_report_dates_include_previous_days(db_session: Session) -> None:
    stale_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    db_session.add(
        ScheduledReportJob(
            schedule_key=f"daily_global_update:{SCHEDULE_DATE.isoformat()}",
            job_name="daily_global_update",
            scheduled_for=datetime(2026, 8, 31, 6, 0, 0),
            status="running",
            source_environment="test",
            source_name="dead-worker",
            source_hostname="dead-host",
            source_path="/old",
            started_at=stale_at,
            created_at=stale_at,
            updated_at=stale_at,
        )
    )
    db_session.commit()

    dates = list_stale_daily_report_dates(
        db_session,
        _settings(scheduled_reports_recovery_seconds=60),
    )

    assert dates == [SCHEDULE_DATE]


def test_run_due_checks_existing_daily_slot_for_safe_recovery() -> None:
    settings = _settings()
    daily_row = SimpleNamespace(status="completed")
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = MagicMock()

    with (
        patch("backend.src.jobs.run_report_scheduler.get_settings", return_value=settings),
        patch(
            "backend.src.jobs.run_report_scheduler.resolve_job_source",
            return_value=SOURCE,
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.SessionLocal",
            session_factory,
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.list_stale_daily_report_dates",
            return_value=[date(2026, 9, 1)],
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.run_daily_scheduled_report",
            side_effect=[(daily_row, True), (daily_row, False)],
        ) as daily,
    ):
        results = run_due(datetime(2026, 9, 2, 12, 0, tzinfo=ZoneInfo("Europe/Rome")))

    assert results == [("daily_global_update", 0)]
    assert daily.call_count == 2
    assert daily.call_args_list[0].kwargs["scheduled_date"] == date(2026, 9, 1)
    assert daily.call_args_list[1].kwargs["scheduled_date"] == date(2026, 9, 2)


def test_run_due_starts_weekly_cascade_on_monday_after_cutoff() -> None:
    settings = _settings()
    daily_row = SimpleNamespace(status="completed")
    weekly_row = SimpleNamespace(status="completed")
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = MagicMock()

    with (
        patch("backend.src.jobs.run_report_scheduler.get_settings", return_value=settings),
        patch(
            "backend.src.jobs.run_report_scheduler.resolve_job_source",
            return_value=SOURCE,
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.SessionLocal",
            session_factory,
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.list_stale_daily_report_dates",
            return_value=[],
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.run_daily_scheduled_report",
            return_value=(daily_row, True),
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.get_scheduled_job",
            return_value=None,
        ) as existing,
        patch(
            "backend.src.jobs.run_report_scheduler.run_weekly_scheduled_report",
            return_value=(weekly_row, True),
        ) as weekly,
    ):
        results = run_due(datetime(2026, 8, 31, 10, 5, tzinfo=ZoneInfo("Europe/Rome")))

    assert results == [("daily_global_update", 0), ("weekly_validation", 0)]
    weekly.assert_called_once()
    assert weekly.call_args.kwargs["scheduled_date"] == date(2026, 8, 31)
    existing.assert_called_once()


def test_run_due_skips_weekly_when_slot_already_claimed() -> None:
    settings = _settings()
    daily_row = SimpleNamespace(status="completed")
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = MagicMock()

    with (
        patch("backend.src.jobs.run_report_scheduler.get_settings", return_value=settings),
        patch(
            "backend.src.jobs.run_report_scheduler.resolve_job_source",
            return_value=SOURCE,
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.SessionLocal",
            session_factory,
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.list_stale_daily_report_dates",
            return_value=[],
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.run_daily_scheduled_report",
            return_value=(daily_row, True),
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.get_scheduled_job",
            return_value=SimpleNamespace(id=9, status="completed"),
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.run_weekly_scheduled_report",
        ) as weekly,
    ):
        results = run_due(datetime(2026, 8, 31, 10, 5, tzinfo=ZoneInfo("Europe/Rome")))

    assert results == [("daily_global_update", 0)]
    weekly.assert_not_called()


def test_run_due_does_not_start_weekly_before_monday_cutoff() -> None:
    settings = _settings()
    daily_row = SimpleNamespace(status="completed")
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = MagicMock()

    with (
        patch("backend.src.jobs.run_report_scheduler.get_settings", return_value=settings),
        patch(
            "backend.src.jobs.run_report_scheduler.resolve_job_source",
            return_value=SOURCE,
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.SessionLocal",
            session_factory,
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.list_stale_daily_report_dates",
            return_value=[],
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.run_daily_scheduled_report",
            return_value=(daily_row, True),
        ),
        patch("backend.src.jobs.run_report_scheduler.get_scheduled_job") as existing,
        patch(
            "backend.src.jobs.run_report_scheduler.run_weekly_scheduled_report",
        ) as weekly,
    ):
        results = run_due(datetime(2026, 8, 31, 9, 59, tzinfo=ZoneInfo("Europe/Rome")))

    assert results == [("daily_global_update", 0)]
    existing.assert_not_called()
    weekly.assert_not_called()


def test_weekly_success_links_calibration_to_new_walk_forward(db_session: Session) -> None:
    def start_global(db: Session, **_kwargs):
        return _global_run(db), "ok"

    daily, _ = run_daily_scheduled_report(
        db_session,
        _settings(),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        global_update_starter=start_global,
    )
    assert daily.status == "completed"

    def start_wf(db: Session, **_kwargs):
        return _walk_forward_run(db), True, "ok"

    seen_walk_forward_id: list[int] = []

    def start_calibration(db: Session, *, request, **_kwargs):
        assert request.walk_forward_run_id is not None
        seen_walk_forward_id.append(request.walk_forward_run_id)
        return (
            _calibration_run(db, walk_forward_run_id=request.walk_forward_run_id),
            True,
            "ok",
        )

    weekly, claimed = run_weekly_scheduled_report(
        db_session,
        _settings(),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        walk_forward_starter=start_wf,
        calibration_starter=start_calibration,
    )

    assert claimed is True
    assert weekly.status == "completed"
    assert weekly.global_update_run_id == daily.global_update_run_id
    assert weekly.walk_forward_run_id == seen_walk_forward_id[0]
    assert weekly.calibration_run_id is not None


def test_calibration_model_error_lines_extracts_extra_market_failures() -> None:
    lines = calibration_model_error_lines(
        {
            "models_detail": [
                {
                    "model_version": "v4",
                    "model_name": "voting_ensemble",
                    "leakage_flags": [],
                    "comparison": {"raw": {"ece": 0.0047}},
                },
                {
                    "model_version": "first_set_winner_v2",
                    "model_name": "logistic_regression",
                    "leakage_flags": [
                        "error:Versione modello sconosciuta: first_set_winner_v2"
                    ],
                    "comparison": {
                        "error": "Versione modello sconosciuta: first_set_winner_v2"
                    },
                },
            ]
        }
    )
    assert lines == [
        "- first_set_winner_v2/logistic_regression: "
        "Versione modello sconosciuta: first_set_winner_v2"
    ]


def test_weekly_email_lists_calibration_model_errors(
    db_session: Session, monkeypatch
) -> None:
    def start_global(db: Session, **_kwargs):
        return _global_run(db), "ok"

    run_daily_scheduled_report(
        db_session,
        _settings(),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        global_update_starter=start_global,
    )

    def start_wf(db: Session, **_kwargs):
        return _walk_forward_run(db), True, "ok"

    def start_calibration(db: Session, *, request, **_kwargs):
        run = _calibration_run(
            db,
            walk_forward_run_id=request.walk_forward_run_id,
            status="completed_with_errors",
        )
        run.summary_json = (
            '{"models_detail":[{"model_version":"over_under_games_v1",'
            '"model_name":"random_forest","leakage_flags":'
            '["error:Versione modello sconosciuta: over_under_games_v1"],'
            '"comparison":{"error":"Versione modello sconosciuta: over_under_games_v1"}}]}'
        )
        db.commit()
        return run, True, "Calibrazione completata."

    captured: dict[str, str] = {}

    def fake_send(_settings, *, subject, body, attachments):
        captured["body"] = body
        captured["subject"] = subject
        return {"status": "disabled"}

    monkeypatch.setattr(
        "backend.src.app.services.scheduled_reports.send_report_email",
        fake_send,
    )

    weekly, _ = run_weekly_scheduled_report(
        db_session,
        _settings(),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        walk_forward_starter=start_wf,
        calibration_starter=start_calibration,
    )

    assert weekly.status == "failed"
    assert "Errori modelli calibrazione:" in captured["body"]
    assert "over_under_games_v1/random_forest" in captured["body"]


def test_weekly_skips_calibration_when_walk_forward_fails(db_session: Session) -> None:
    def start_global(db: Session, **_kwargs):
        return _global_run(db), "ok"

    run_daily_scheduled_report(
        db_session,
        _settings(),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        global_update_starter=start_global,
    )

    def start_wf(db: Session, **_kwargs):
        return _walk_forward_run(db, status="failed"), True, "broken"

    calibration = MagicMock()
    weekly, _ = run_weekly_scheduled_report(
        db_session,
        _settings(),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        walk_forward_starter=start_wf,
        calibration_starter=calibration,
    )

    assert weekly.status == "failed"
    assert weekly.calibration_run_id is None
    assert "non avviata" in (weekly.message or "").lower()
    calibration.assert_not_called()


def test_weekly_requires_strict_daily_completed_status(db_session: Session) -> None:
    def start_global(db: Session, **_kwargs):
        return _global_run(db, status="completed_with_errors"), "partial"

    run_daily_scheduled_report(
        db_session,
        _settings(),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        global_update_starter=start_global,
    )

    walk_forward = MagicMock()
    weekly, _ = run_weekly_scheduled_report(
        db_session,
        _settings(),
        scheduled_date=SCHEDULE_DATE,
        source=SOURCE,
        walk_forward_starter=walk_forward,
        calibration_starter=MagicMock(),
    )

    assert weekly.status == "skipped"
    assert "completed_with_errors" in (weekly.message or "")
    walk_forward.assert_not_called()


def test_email_delivery_uses_resend_https_and_base64_attachment() -> None:
    settings = _settings(
        report_email_enabled=True,
        report_email_to="trottarosario@gmail.com",
        resend_api_key="re_not_real",
        resend_api_base="https://api.resend.com",
        resend_from="Tennis Oracle <onboarding@resend.dev>",
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    response = MagicMock()
    response.json.return_value = {"id": "email_123"}
    client.post.return_value = response

    with patch("backend.src.app.observability.email_reports.httpx.Client", return_value=client):
        result = send_report_email(
            settings,
            subject="Test report",
            body="body",
            attachments=(EmailAttachment("report.json", b"{}"),),
        )

    assert result["status"] == "sent"
    assert result["provider_message_id"] == "email_123"
    request = client.post.call_args
    assert request.args[0] == "https://api.resend.com/emails"
    assert request.kwargs["headers"]["Authorization"] == "Bearer re_not_real"
    assert request.kwargs["json"]["to"] == ["trottarosario@gmail.com"]
    assert request.kwargs["json"]["attachments"] == [
        {"filename": "report.json", "content": "e30="}
    ]


def test_email_error_never_exposes_resend_api_key() -> None:
    secret = "re_super_secret_api_key"
    settings = _settings(
        report_email_enabled=True,
        report_email_to="trottarosario@gmail.com",
        resend_api_key=secret,
        resend_from="Tennis Oracle <onboarding@resend.dev>",
    )

    with patch(
        "backend.src.app.observability.email_reports.httpx.Client",
        side_effect=RuntimeError(f"provider echoed {secret}"),
    ):
        result = send_report_email(settings, subject="Test", body="body")

    assert result["status"] == "error"
    assert secret not in str(result.get("error"))


def test_email_enabled_without_resend_api_key_fails_closed() -> None:
    settings = _settings(
        report_email_enabled=True,
        report_email_to="trottarosario@gmail.com",
        resend_api_key=None,
        resend_from="Tennis Oracle <onboarding@resend.dev>",
    )

    with patch("backend.src.app.observability.email_reports.httpx.Client") as client:
        result = send_report_email(settings, subject="Test", body="body")

    assert result["status"] == "configuration_error"
    assert "RESEND_API_KEY" in str(result.get("error"))
    client.assert_not_called()
