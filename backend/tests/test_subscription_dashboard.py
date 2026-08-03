"""Tests for SUB-06 subscriptions dashboard admin APIs."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from backend.src.app.services.subscriptions import (
    PLAN_FREE,
    PLAN_FOUNDER,
    PLAN_PRO,
    cancel_subscription,
    create_subscription,
    get_or_create_user,
    seed_default_plans,
)
from backend.src.entity.admin_audit_log import AdminAuditLog
from backend.src.entity.subscription import PaymentEvent


def _seed_dashboard_data(db_session):
    base_time = datetime(2026, 8, 2, 9, 0, 0)
    seed_default_plans(db_session)

    free_user = get_or_create_user(
        db_session,
        telegram_user_id=81001,
        username="free_user",
        now=base_time - timedelta(days=25),
    )
    create_subscription(
        db_session,
        user_id=free_user.id,
        plan_code=PLAN_FREE,
        started_at=base_time - timedelta(days=25),
        trial_days=0,
        period_days=None,
        now=base_time - timedelta(days=25),
    )

    pro_user = get_or_create_user(
        db_session,
        telegram_user_id=81002,
        username="pro_user",
        now=base_time - timedelta(days=20),
    )
    pro_subscription = create_subscription(
        db_session,
        user_id=pro_user.id,
        plan_code=PLAN_PRO,
        started_at=base_time - timedelta(days=20),
        trial_days=0,
        period_days=30,
        now=base_time - timedelta(days=20),
    )

    trial_user = get_or_create_user(
        db_session,
        telegram_user_id=81003,
        username="trial_user",
        now=base_time - timedelta(days=1),
    )
    create_subscription(
        db_session,
        user_id=trial_user.id,
        plan_code=PLAN_PRO,
        started_at=base_time - timedelta(days=1),
        trial_days=7,
        period_days=30,
        now=base_time - timedelta(days=1),
    )

    founder_user = get_or_create_user(
        db_session,
        telegram_user_id=81004,
        username="founder_user",
        now=base_time - timedelta(days=10),
    )
    create_subscription(
        db_session,
        user_id=founder_user.id,
        plan_code=PLAN_FOUNDER,
        started_at=base_time - timedelta(days=10),
        trial_days=0,
        period_days=365,
        now=base_time - timedelta(days=10),
    )

    converted_user = get_or_create_user(
        db_session,
        telegram_user_id=81005,
        username="converted_user",
        now=base_time - timedelta(days=60),
    )
    create_subscription(
        db_session,
        user_id=converted_user.id,
        plan_code=PLAN_FREE,
        started_at=base_time - timedelta(days=60),
        trial_days=0,
        period_days=None,
        now=base_time - timedelta(days=60),
    )
    create_subscription(
        db_session,
        user_id=converted_user.id,
        plan_code=PLAN_PRO,
        started_at=base_time - timedelta(days=5),
        trial_days=0,
        period_days=30,
        now=base_time - timedelta(days=5),
    )

    canceled_user = get_or_create_user(
        db_session,
        telegram_user_id=81006,
        username="canceled_user",
        now=base_time - timedelta(days=15),
    )
    canceled_sub = create_subscription(
        db_session,
        user_id=canceled_user.id,
        plan_code=PLAN_PRO,
        started_at=base_time - timedelta(days=15),
        trial_days=0,
        period_days=30,
        now=base_time - timedelta(days=15),
    )
    cancel_subscription(
        db_session,
        canceled_sub.id,
        immediate=True,
        reason="user_request",
        now=base_time - timedelta(days=2),
    )

    db_session.add(
        PaymentEvent(
            subscription_id=pro_subscription.id,
            user_id=pro_user.id,
            provider="stripe",
            provider_event_id="evt_failed_sub_dashboard_1",
            event_type="invoice_payment_failed",
            status="failed",
            amount_cents=1900,
            currency="EUR",
            event_at=base_time - timedelta(days=1),
            raw_payload_json="{}",
            created_at=base_time - timedelta(days=1),
        )
    )
    db_session.commit()

    return {
        "pro_subscription_id": pro_subscription.id,
        "pro_user_id": pro_user.id,
    }


def test_subscription_dashboard_requires_admin(client):
    assert client.get("/api/subscriptions/dashboard/summary").status_code == 401
    assert client.get("/api/subscriptions/dashboard/users").status_code == 401
    assert client.get("/api/subscriptions/dashboard/events").status_code == 401
    assert client.get("/api/subscriptions/dashboard/export.csv").status_code == 401


def test_subscription_dashboard_summary_users_events_export(client, auth_headers, db_session):
    _seed_dashboard_data(db_session)

    summary = client.get(
        "/api/subscriptions/dashboard/summary",
        headers=auth_headers,
        params={"months": 6},
    )
    assert summary.status_code == 200
    overview = summary.json()["overview"]
    assert overview["users_free"] >= 1
    assert overview["users_pro"] >= 1
    assert overview["users_founder"] >= 1
    assert overview["active_subscriptions"] >= 1
    assert overview["trialing_subscriptions"] >= 1
    assert overview["payment_failed_last_30_days"] >= 1
    assert overview["free_to_pro_users"] >= 1
    assert overview["free_user_base"] >= 1

    monthly = summary.json()["monthly_revenue"]
    assert len(monthly) >= 1

    users = client.get(
        "/api/subscriptions/dashboard/users",
        headers=auth_headers,
        params={"plan_code": "pro", "q": "pro_user"},
    )
    assert users.status_code == 200
    payload = users.json()
    assert payload["total"] >= 1
    assert any((row["username"] or "") == "pro_user" for row in payload["items"])

    failed_only = client.get(
        "/api/subscriptions/dashboard/users",
        headers=auth_headers,
        params={"payment_failed": "true"},
    )
    assert failed_only.status_code == 200
    assert failed_only.json()["total"] >= 1

    events = client.get(
        "/api/subscriptions/dashboard/events",
        headers=auth_headers,
        params={"source": "payment"},
    )
    assert events.status_code == 200
    event_items = events.json()["items"]
    assert any(item["source"] == "payment" for item in event_items)

    csv_export = client.get(
        "/api/subscriptions/dashboard/export.csv",
        headers=auth_headers,
        params={"plan_code": "pro"},
    )
    assert csv_export.status_code == 200
    assert csv_export.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in csv_export.headers.get("content-disposition", "")
    csv_text = csv_export.text
    assert "user_id,telegram_user_id,username" in csv_text

    db_session.expire_all()
    export_logs = db_session.scalars(
        select(AdminAuditLog).where(AdminAuditLog.action == "subscriptions_export_csv")
    ).all()
    assert len(export_logs) >= 1


def test_subscription_dashboard_manual_actions_are_audited(client, auth_headers, db_session):
    data = _seed_dashboard_data(db_session)
    target_subscription_id = data["pro_subscription_id"]

    suspended = client.post(
        f"/api/subscriptions/dashboard/subscriptions/{target_subscription_id}/suspend",
        headers=auth_headers,
        json={"reason": "manual_review"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["subscription"]["status"] == "suspended"

    resumed = client.post(
        f"/api/subscriptions/dashboard/subscriptions/{target_subscription_id}/resume",
        headers=auth_headers,
    )
    assert resumed.status_code == 200
    assert resumed.json()["subscription"]["status"] in {"active", "trialing"}

    canceled = client.post(
        f"/api/subscriptions/dashboard/subscriptions/{target_subscription_id}/cancel",
        headers=auth_headers,
        json={"immediate": True, "reason": "fraud_check"},
    )
    assert canceled.status_code == 200
    assert canceled.json()["subscription"]["status"] == "canceled"

    db_session.expire_all()
    logs = db_session.scalars(
        select(AdminAuditLog)
        .where(AdminAuditLog.target_id == str(target_subscription_id))
        .order_by(AdminAuditLog.id.asc())
    ).all()
    actions = [row.action for row in logs]
    assert "subscription_suspend" in actions
    assert "subscription_resume" in actions
    assert "subscription_cancel" in actions

    events = client.get(
        "/api/subscriptions/dashboard/events",
        headers=auth_headers,
        params={"source": "admin_action", "subscription_id": target_subscription_id},
    )
    assert events.status_code == 200
    event_items = events.json()["items"]
    assert any(item["source"] == "admin_action" for item in event_items)

