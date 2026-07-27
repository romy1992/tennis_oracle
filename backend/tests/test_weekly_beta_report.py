"""Tests for weekly beta report compute, persistence, and admin API."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

from backend.src.app.services.telegram_analytics import record_telegram_event
from backend.src.app.services.weekly_beta_report import (
    compute_weekly_beta_report_payload,
    format_admin_telegram_summary,
    generate_and_store_weekly_beta_report,
    iso_week_bounds,
    previous_completed_iso_week,
    report_to_read,
)
from backend.src.entity.global_update_run import GlobalUpdateRun
from backend.src.entity.telegram_feedback import TelegramFeedback
from backend.src.entity.telegram_notification_delivery import TelegramNotificationDelivery
from backend.src.entity.telegram_user import TelegramUser


def _monday(d: date | None = None) -> date:
    ref = d or date(2026, 7, 20)  # Monday
    start, _ = iso_week_bounds(ref)
    return start


def _add_user(
    db,
    *,
    telegram_user_id: int,
    created_at: datetime,
    first_access_at: datetime | None = None,
    last_access_at: datetime | None = None,
    status: str = "active",
) -> TelegramUser:
    first = first_access_at or created_at
    last = last_access_at or first
    row = TelegramUser(
        telegram_user_id=telegram_user_id,
        chat_id=telegram_user_id,
        username=f"u{telegram_user_id}",
        status=status,
        first_access_at=first,
        last_access_at=last,
        terms_accepted=True,
        notifications_enabled=True,
        notify_predictions=True,
        notify_results=True,
        notify_empty_day=False,
        created_at=created_at,
        updated_at=last,
    )
    db.add(row)
    db.commit()
    return row


def test_iso_week_bounds_and_previous_week():
    start, end = iso_week_bounds(date(2026, 7, 22))  # Wednesday
    assert start == date(2026, 7, 20)
    assert end == date(2026, 7, 26)
    prev_start, prev_end = previous_completed_iso_week(today=date(2026, 7, 27))
    assert prev_start == date(2026, 7, 20)
    assert prev_end == date(2026, 7, 26)


def test_compute_weekly_beta_report_metrics(db_session):
    week_start = date(2026, 7, 13)  # Monday W29
    week_end = date(2026, 7, 19)
    prev_start = date(2026, 7, 6)

    # Cohort for retention: first access previous week, last access current week.
    _add_user(
        db_session,
        telegram_user_id=101,
        created_at=datetime(2026, 7, 7, 10, 0),
        first_access_at=datetime(2026, 7, 7, 10, 0),
        last_access_at=datetime(2026, 7, 15, 12, 0),
    )
    # New + active this week
    _add_user(
        db_session,
        telegram_user_id=102,
        created_at=datetime(2026, 7, 14, 9, 0),
        last_access_at=datetime(2026, 7, 16, 9, 0),
    )
    # Previous-week only (not retained)
    _add_user(
        db_session,
        telegram_user_id=103,
        created_at=datetime(2026, 7, 8, 9, 0),
        first_access_at=datetime(2026, 7, 8, 9, 0),
        last_access_at=datetime(2026, 7, 9, 9, 0),
    )

    record_telegram_event(
        db=db_session,
        event_type="command",
        action="/oggi",
        telegram_user_id=102,
        created_at=datetime(2026, 7, 15, 11, 0),
    )

    db_session.add(
        GlobalUpdateRun(
            run_date=week_start + timedelta(days=1),
            origin="job",
            status="completed_with_errors",
            force="false",
            cancel_requested="false",
            sync_cloud="false",
            combinations_failed=2,
            created_at=datetime(2026, 7, 14, 8, 0),
            errors_json='["combo boom"]',
        )
    )
    db_session.add(
        TelegramNotificationDelivery(
            dedupe_key="predictions:2026-07-14:102",
            kind="predictions",
            content_date=date(2026, 7, 14),
            telegram_user_id=102,
            chat_id=102,
            status="failed",
            attempt_count=2,
            last_error="timeout",
            created_at=datetime(2026, 7, 14, 9, 15),
            updated_at=datetime(2026, 7, 14, 9, 15),
        )
    )
    db_session.add(
        TelegramFeedback(
            telegram_user_id=102,
            username="u102",
            category="bug",
            rating=4,
            message="Problema test",
            status="new",
            created_at=datetime(2026, 7, 15, 18, 0),
            updated_at=datetime(2026, 7, 15, 18, 0),
        )
    )
    db_session.commit()

    payload = compute_weekly_beta_report_payload(
        db_session, week_start=week_start, week_end=week_end
    )
    assert payload.current.week_label == "2026-W29"
    assert payload.current.users.total_users == 3
    assert payload.current.users.new_users == 1
    assert payload.current.users.active_users == 2  # 101 + 102
    assert payload.current.users.retention_cohort == 2  # 101 + 103
    assert payload.current.users.retention_retained == 1  # 101
    assert payload.current.users.retention_pct == 50.0
    assert payload.current.command_usage.total_events >= 1
    assert payload.current.pipeline.runs_completed_with_errors == 1
    assert payload.current.pipeline.combinations_failed == 2
    assert any("combo boom" in m for m in payload.current.pipeline.error_messages)
    assert payload.current.notifications.failed == 1
    assert payload.current.feedback.total == 1
    assert payload.previous.week_start == prev_start
    assert payload.wow.active_users.current == 2

    summary = format_admin_telegram_summary(payload)
    assert "Report beta settimanale 2026-W29" in summary
    assert "Retention W1" in summary


def test_generate_and_store_idempotent(db_session):
    week_start = _monday(date(2026, 7, 13))
    with patch(
        "backend.src.app.services.weekly_beta_report.send_admin_alert",
        return_value={"sent": True, "telegram": "ok", "skipped": False},
    ) as alert:
        row1, created1, tg1 = generate_and_store_weekly_beta_report(
            db_session,
            week_start=week_start,
            send_telegram=True,
            force=False,
            generated_by="test",
        )
        assert created1 is True
        assert tg1.get("sent") is True
        assert row1.telegram_status == "sent"
        assert alert.call_count == 1

        row2, created2, _tg2 = generate_and_store_weekly_beta_report(
            db_session,
            week_start=week_start,
            send_telegram=False,
            force=False,
            generated_by="test",
        )
        assert created2 is False
        assert row2.id == row1.id
        assert alert.call_count == 1

        row3, created3, _tg3 = generate_and_store_weekly_beta_report(
            db_session,
            week_start=week_start,
            send_telegram=True,
            force=True,
            generated_by="test",
        )
        assert created3 is False
        assert row3.id == row1.id
        assert alert.call_count == 2
        read = report_to_read(row3)
        assert read.payload.current.week_start == week_start


class TestWeeklyBetaReportApi:
    def test_generate_list_and_get(self, client, auth_headers, db_session):
        week_start = date(2026, 7, 13)
        with patch(
            "backend.src.app.services.weekly_beta_report.send_admin_alert",
            return_value={"sent": False, "skipped": True, "reason": "alerts_disabled"},
        ):
            response = client.post(
                "/api/weekly-beta-reports/generate",
                headers=auth_headers,
                json={
                    "week_start": week_start.isoformat(),
                    "send_telegram": True,
                    "force": False,
                },
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["created"] is True
        report_id = body["report"]["id"]
        assert body["report"]["week_label"] == "2026-W29"

        listed = client.get("/api/weekly-beta-reports", headers=auth_headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        latest = client.get("/api/weekly-beta-reports/latest", headers=auth_headers)
        assert latest.status_code == 200
        assert latest.json()["id"] == report_id

        detail = client.get(f"/api/weekly-beta-reports/{report_id}", headers=auth_headers)
        assert detail.status_code == 200
        assert "wow" in detail.json()["payload"]

    def test_requires_admin(self, client):
        response = client.get("/api/weekly-beta-reports")
        assert response.status_code in (401, 403)
