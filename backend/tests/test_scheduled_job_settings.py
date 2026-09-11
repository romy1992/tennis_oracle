"""Admin scheduled-job settings and overlay behaviour."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.src.app.services.scheduled_job_settings import (
    DAILY_JOB_KEY,
    TELEGRAM_JOB_KEY,
    WEEKLY_JOB_KEY,
    get_effective_schedule,
    list_scheduled_jobs,
    run_auxiliary_jobs,
    update_scheduled_job,
)
from backend.src.entity.admin_audit_log import AdminAuditLog
from backend.src.entity.scheduled_job_setting import ScheduledJobSetting
from backend.src.jobs.run_report_scheduler import run_due
from backend.tests.auth_helpers import make_test_settings, override_settings
from backend.tests.test_scheduled_reports import SOURCE


def _session_box(db_session):
    class _SessionBox:
        def __enter__(self):
            return db_session

        def __exit__(self, *_exc):
            return False

    return _SessionBox()



def test_scheduled_jobs_require_admin(client):
    assert client.get("/api/settings/scheduled-jobs").status_code == 401
    assert (
        client.patch(
            "/api/settings/scheduled-jobs/daily_global_update",
            json={"enabled": True},
        ).status_code
        == 401
    )


def test_list_scheduled_jobs_uses_environment_defaults(client, auth_headers):
    override_settings(
        make_test_settings(
            scheduled_reports_enabled=True,
            scheduled_global_update_time="08:00",
            scheduled_weekly_validation_time="10:00",
            scheduled_weekly_validation_day=0,
            betting_slip_live_poll_enabled=False,
            betting_slip_live_poll_interval_seconds=180,
        )
    )

    response = client.get("/api/settings/scheduled-jobs", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["timezone"] == "Europe/Rome"
    keys = [item["job_key"] for item in payload["items"]]
    assert keys == [
        "daily_global_update",
        "weekly_validation",
        "betting_slip_live_poll",
        "betting_slip_recap",
        "telegram_notifications",
        "weekly_beta_report",
        "closing_odds_capture",
        "ops_checks",
        "db_backup",
    ]
    daily = payload["items"][0]
    assert daily["enabled"] is True
    assert daily["clock_time"] == "08:00"
    assert daily["source"] == "environment"
    live = next(item for item in payload["items"] if item["job_key"] == "betting_slip_live_poll")
    assert live["enabled"] is False
    assert live["interval_seconds"] == 180
    assert live["schedule_kind"] == "interval"


def test_admin_can_toggle_and_reschedule_job(client, auth_headers, db_session):
    override_settings(make_test_settings(scheduled_reports_enabled=True))

    response = client.patch(
        "/api/settings/scheduled-jobs/daily_global_update",
        headers=auth_headers,
        json={"enabled": False, "clock_time": "07:15"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["clock_time"] == "07:15"
    assert payload["source"] == "database"

    row = db_session.get(ScheduledJobSetting, "daily_global_update")
    assert row is not None
    assert row.enabled is False
    assert row.clock_time == "07:15"

    listed = client.get("/api/settings/scheduled-jobs", headers=auth_headers).json()
    daily = listed["items"][0]
    assert daily["enabled"] is False
    assert daily["clock_time"] == "07:15"

    audit = db_session.scalar(
        select(AdminAuditLog)
        .where(AdminAuditLog.action == "scheduled_job_update")
        .order_by(AdminAuditLog.id.desc())
    )
    assert audit is not None
    assert audit.target_id == "daily_global_update"


def test_interval_below_minimum_is_rejected(client, auth_headers):
    response = client.patch(
        "/api/settings/scheduled-jobs/betting_slip_live_poll",
        headers=auth_headers,
        json={"interval_seconds": 5},
    )
    assert response.status_code == 422
    assert "Intervallo minimo" in response.json()["detail"]


def test_unknown_job_returns_404(client, auth_headers):
    response = client.patch(
        "/api/settings/scheduled-jobs/not-a-real-job",
        headers=auth_headers,
        json={"enabled": True},
    )
    assert response.status_code == 404


def test_get_effective_schedule_ignores_non_row_query_results(db_session):
    settings = make_test_settings(scheduled_reports_enabled=False)
    fake_db = MagicMock()
    fake_db.get.return_value = MagicMock()

    overlay = get_effective_schedule(fake_db, settings, DAILY_JOB_KEY)

    assert overlay.source == "environment"
    assert overlay.enabled is False
    assert overlay.clock_time == "08:00"


def test_run_due_skips_disabled_daily_and_weekly_jobs() -> None:
    settings = make_test_settings(
        scheduled_reports_enabled=False,
        scheduled_reports_timezone="Europe/Rome",
        scheduled_global_update_time="08:00",
        scheduled_weekly_validation_day=0,
        scheduled_weekly_validation_time="10:00",
    )
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = MagicMock()
    disabled = MagicMock(
        enabled=False,
        clock_time="08:00",
        weekday=0,
    )

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
            "backend.src.jobs.run_report_scheduler.get_effective_schedule",
            return_value=disabled,
        ),
        patch(
            "backend.src.jobs.run_report_scheduler.run_daily_scheduled_report",
        ) as daily,
        patch(
            "backend.src.jobs.run_report_scheduler.run_weekly_scheduled_report",
        ) as weekly,
    ):
        results = run_due(datetime(2026, 8, 31, 10, 5, tzinfo=ZoneInfo("Europe/Rome")))

    assert results == []
    daily.assert_not_called()
    weekly.assert_not_called()


def test_run_due_uses_database_clock_overlay(db_session) -> None:
    settings = make_test_settings(
        scheduled_reports_enabled=True,
        scheduled_reports_timezone="Europe/Rome",
        scheduled_global_update_time="08:00",
        scheduled_weekly_validation_day=0,
        scheduled_weekly_validation_time="10:00",
        report_email_enabled=False,
    )
    update_scheduled_job(
        db_session,
        settings,
        job_key=DAILY_JOB_KEY,
        clock_time="09:30",
        updated_by="admin",
    )
    overlay = get_effective_schedule(db_session, settings, DAILY_JOB_KEY)
    assert overlay.clock_time == "09:30"
    assert overlay.source == "database"


def test_run_auxiliary_jobs_runs_due_clock_job(db_session):
    settings = make_test_settings(
        scheduled_reports_timezone="Europe/Rome",
        telegram_notifications_enabled=True,
    )
    override_settings(settings)
    update_scheduled_job(
        db_session,
        settings,
        job_key=TELEGRAM_JOB_KEY,
        enabled=True,
        clock_time="08:30",
        updated_by="admin",
    )

    with (
        patch(
            "backend.src.app.db.session.SessionLocal",
            return_value=_session_box(db_session),
        ),
        patch(
            "backend.src.app.services.scheduled_job_settings.execute_scheduled_job",
            return_value="completed",
        ) as execute,
    ):
        results = run_auxiliary_jobs(
            datetime(2026, 8, 31, 8, 45, tzinfo=ZoneInfo("Europe/Rome"))
        )

    assert results == [(TELEGRAM_JOB_KEY, "completed")]
    execute.assert_called_once()
    db_session.expire_all()
    row = db_session.get(ScheduledJobSetting, TELEGRAM_JOB_KEY)
    assert row is not None
    assert row.last_run_status == "completed"


def test_run_auxiliary_jobs_skips_before_clock(db_session):
    settings = make_test_settings(
        scheduled_reports_timezone="Europe/Rome",
        telegram_notifications_enabled=True,
    )
    override_settings(settings)
    update_scheduled_job(
        db_session,
        settings,
        job_key=TELEGRAM_JOB_KEY,
        enabled=True,
        clock_time="08:30",
        updated_by="admin",
    )

    with (
        patch(
            "backend.src.app.db.session.SessionLocal",
            return_value=_session_box(db_session),
        ),
        patch(
            "backend.src.app.services.scheduled_job_settings.execute_scheduled_job",
            return_value="completed",
        ) as execute,
    ):
        results = run_auxiliary_jobs(
            datetime(2026, 8, 31, 8, 10, tzinfo=ZoneInfo("Europe/Rome"))
        )

    assert results == []
    execute.assert_not_called()


def test_list_scheduled_jobs_includes_weekly_weekday(db_session):
    settings = make_test_settings(
        scheduled_reports_enabled=True,
        scheduled_weekly_validation_day=0,
    )
    items = list_scheduled_jobs(db_session, settings)
    weekly = next(item for item in items if item.job_key == WEEKLY_JOB_KEY)
    assert weekly.weekday == 0
    assert weekly.schedule_kind == "weekly_clock"
