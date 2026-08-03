"""Tests for subscription domain models and service lifecycle."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from sqlalchemy import func, select

from backend.src.app.services.subscriptions import (
    PLAN_FOUNDER,
    PLAN_FREE,
    PLAN_PRO,
    TELEGRAM_ENTITLEMENT_FREE,
    TELEGRAM_ENTITLEMENT_PARTITE,
    cancel_subscription,
    check_user_entitlement,
    create_subscription,
    expire_due_subscriptions,
    get_telegram_subscription_snapshot,
    get_or_create_user,
    renew_subscription,
    seed_default_plans,
    suspend_subscription,
)
from backend.src.entity.subscription import AccessLog, PaymentEvent, Plan, Subscription
from backend.tests.db_helpers import create_session_factory, create_test_engine


class SubscriptionsServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_seed_default_plans_is_idempotent(self):
        with self.Session() as session:
            first = seed_default_plans(session)
            second = seed_default_plans(session)

            self.assertEqual([plan.code for plan in first], [PLAN_FREE, PLAN_PRO, PLAN_FOUNDER])
            self.assertEqual([plan.code for plan in second], [PLAN_FREE, PLAN_PRO, PLAN_FOUNDER])

            count = int(session.scalar(select(func.count()).select_from(Plan)) or 0)
            self.assertEqual(count, 3)

            free = session.scalar(select(Plan).where(Plan.code == PLAN_FREE))
            self.assertIsNotNone(free)
            assert free is not None
            free_entitlements = {row.code: bool(row.is_enabled) for row in free.entitlements}
            self.assertTrue(free_entitlements[TELEGRAM_ENTITLEMENT_FREE])
            self.assertFalse(free_entitlements["telegram.command.partite"])
            self.assertFalse(free_entitlements["telegram.command.schedine"])
            self.assertFalse(free_entitlements["telegram.command.statistiche"])
            self.assertFalse(free_entitlements["feature.value_bet.deep_metrics"])

    def test_subscription_lifecycle_trial_renew_cancel_suspend_expire(self):
        start_at = datetime(2026, 8, 1, 9, 0, 0)

        with self.Session() as session:
            seed_default_plans(session)
            user = get_or_create_user(
                session,
                telegram_user_id=101,
                username="alice",
                now=start_at,
            )
            created = create_subscription(
                session,
                user_id=user.id,
                plan_code=PLAN_PRO,
                started_at=start_at,
                trial_days=5,
                period_days=30,
                now=start_at,
            )
            self.assertEqual(created.status, "trialing")
            self.assertEqual(created.trial_started_at, start_at)
            self.assertEqual(created.trial_ends_at, start_at + timedelta(days=5))
            self.assertEqual(created.expires_at, start_at + timedelta(days=30))

            renewed = renew_subscription(
                session,
                created.id,
                period_days=30,
                now=start_at + timedelta(days=2),
                amount_cents=1900,
                currency="EUR",
            )
            self.assertEqual(renewed.status, "active")
            self.assertEqual(renewed.current_period_start_at, start_at + timedelta(days=30))
            self.assertEqual(renewed.expires_at, start_at + timedelta(days=60))

            suspended = suspend_subscription(
                session,
                renewed.id,
                reason="manual_review",
                now=start_at + timedelta(days=3),
            )
            self.assertEqual(suspended.status, "suspended")
            self.assertEqual(suspended.suspension_reason, "manual_review")

            cancelled = cancel_subscription(
                session,
                suspended.id,
                immediate=False,
                reason="user_request",
                now=start_at + timedelta(days=4),
            )
            self.assertEqual(cancelled.status, "suspended")
            self.assertTrue(cancelled.cancel_at_period_end)
            self.assertFalse(cancelled.auto_renew)

            expired_count = expire_due_subscriptions(
                session,
                at=start_at + timedelta(days=90),
                commit=True,
            )
            self.assertEqual(expired_count, 1)
            stored = session.scalar(select(Subscription).where(Subscription.id == renewed.id))
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored.status, "expired")

            events = session.scalars(
                select(PaymentEvent)
                .where(PaymentEvent.subscription_id == renewed.id)
                .order_by(PaymentEvent.id.asc())
            ).all()
            self.assertEqual(
                [event.event_type for event in events],
                ["trial_started", "renewed", "suspended", "canceled_at_period_end"],
            )

    def test_entitlement_check_is_plan_driven_and_logs_access(self):
        base_time = datetime(2026, 8, 1, 12, 0, 0)

        with self.Session() as session:
            seed_default_plans(session)

            user = get_or_create_user(
                session,
                telegram_user_id=5001,
                username="beta_user",
                now=base_time,
            )

            denied = check_user_entitlement(
                session,
                user_id=user.id,
                entitlement_code="feature.value_bet.deep_metrics",
                source="telegram",
                resource="/statistiche",
                at=base_time,
            )
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.plan_code, PLAN_FREE)
            self.assertEqual(denied.reason, "missing_entitlement")

            create_subscription(
                session,
                user_id=user.id,
                plan_code=PLAN_PRO,
                started_at=base_time + timedelta(minutes=1),
                trial_days=0,
                period_days=30,
                now=base_time + timedelta(minutes=1),
            )

            allowed = check_user_entitlement(
                session,
                user_id=user.id,
                entitlement_code="feature.value_bet.deep_metrics",
                source="telegram",
                resource="/statistiche",
                at=base_time + timedelta(minutes=2),
            )
            self.assertTrue(allowed.allowed)
            self.assertEqual(allowed.plan_code, PLAN_PRO)

            logs = session.scalars(
                select(AccessLog)
                .where(AccessLog.user_id == user.id)
                .order_by(AccessLog.id.asc())
            ).all()
            self.assertEqual(len(logs), 2)
            self.assertFalse(logs[0].allowed)
            self.assertTrue(logs[1].allowed)
            self.assertEqual(logs[0].entitlement_code, "feature.value_bet.deep_metrics")
            self.assertEqual(logs[0].resource, "/statistiche")

    def test_entitlement_check_can_auto_provision_user_from_telegram_id(self):
        check_time = datetime(2026, 8, 1, 15, 30, 0)

        with self.Session() as session:
            seed_default_plans(session)
            premium = check_user_entitlement(
                session,
                telegram_user_id=9090,
                entitlement_code=TELEGRAM_ENTITLEMENT_PARTITE,
                source="telegram",
                resource="/partite",
                auto_create_user=True,
                at=check_time,
            )
            self.assertFalse(premium.allowed)
            self.assertEqual(premium.plan_code, PLAN_FREE)
            self.assertEqual(premium.reason, "missing_entitlement")

            free = check_user_entitlement(
                session,
                telegram_user_id=9090,
                entitlement_code=TELEGRAM_ENTITLEMENT_FREE,
                source="telegram",
                resource="/help",
                auto_create_user=False,
                at=check_time + timedelta(minutes=1),
            )
            self.assertTrue(free.allowed)
            self.assertEqual(free.plan_code, PLAN_FREE)
            self.assertEqual(free.subscription_status, "active")

    def test_trial_expired_is_denied_even_if_status_is_trialing(self):
        base_time = datetime(2026, 8, 1, 10, 0, 0)

        with self.Session() as session:
            seed_default_plans(session)
            user = get_or_create_user(
                session,
                telegram_user_id=777,
                username="trial_user",
                now=base_time,
            )
            create_subscription(
                session,
                user_id=user.id,
                plan_code=PLAN_PRO,
                started_at=base_time,
                trial_days=1,
                period_days=30,
                now=base_time,
            )

            denied = check_user_entitlement(
                session,
                user_id=user.id,
                entitlement_code=TELEGRAM_ENTITLEMENT_PARTITE,
                source="telegram",
                resource="/partite",
                at=base_time + timedelta(days=2),
            )
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.reason, "trial_expired")
            self.assertIsNotNone(denied.trial_ends_at)

    def test_forced_denial_reason_is_audited(self):
        base_time = datetime(2026, 8, 1, 11, 0, 0)

        with self.Session() as session:
            seed_default_plans(session)
            user = get_or_create_user(
                session,
                telegram_user_id=888,
                username="forced_denied",
                now=base_time,
            )
            create_subscription(
                session,
                user_id=user.id,
                plan_code=PLAN_PRO,
                started_at=base_time,
                trial_days=0,
                period_days=30,
                now=base_time,
            )

            denied = check_user_entitlement(
                session,
                user_id=user.id,
                entitlement_code=TELEGRAM_ENTITLEMENT_PARTITE,
                source="telegram",
                resource="/partite",
                forced_denial_reason="telegram_not_active",
                at=base_time + timedelta(minutes=2),
            )
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.reason, "telegram_not_active")

            latest_log = session.scalars(
                select(AccessLog)
                .where(AccessLog.user_id == user.id)
                .order_by(AccessLog.id.desc())
            ).first()
            self.assertIsNotNone(latest_log)
            assert latest_log is not None
            self.assertFalse(latest_log.allowed)
            self.assertEqual(latest_log.reason, "telegram_not_active")

    def test_snapshot_auto_provisions_free_plan_for_new_telegram_user(self):
        with self.Session() as session:
            seed_default_plans(session)
            snapshot = get_telegram_subscription_snapshot(
                session,
                telegram_user_id=12345001,
                at=datetime(2026, 8, 1, 8, 0, 0),
            )
            self.assertTrue(snapshot.available)
            self.assertEqual(snapshot.plan_code, PLAN_FREE)
            self.assertEqual(snapshot.subscription_status, "active")
            self.assertFalse(snapshot.auto_renew)
            self.assertFalse(snapshot.payment_failed)

    def test_snapshot_flags_failed_payment_and_cancel_at_period_end(self):
        base_time = datetime(2026, 8, 1, 9, 0, 0)

        with self.Session() as session:
            seed_default_plans(session)
            user = get_or_create_user(
                session,
                telegram_user_id=12345002,
                username="snapshot_user",
                now=base_time,
            )
            created = create_subscription(
                session,
                user_id=user.id,
                plan_code=PLAN_PRO,
                started_at=base_time,
                trial_days=0,
                period_days=30,
                now=base_time,
            )
            cancel_subscription(
                session,
                created.id,
                immediate=False,
                reason="user_request",
                now=base_time + timedelta(days=1),
            )

            session.add(
                PaymentEvent(
                    subscription_id=created.id,
                    user_id=user.id,
                    provider="stripe",
                    provider_event_id="evt_failed_snapshot_1",
                    event_type="invoice_payment_failed",
                    status="failed",
                    amount_cents=1900,
                    currency="EUR",
                    event_at=base_time + timedelta(days=2),
                    raw_payload_json="{}",
                    created_at=base_time + timedelta(days=2),
                )
            )
            session.commit()

            snapshot = get_telegram_subscription_snapshot(
                session,
                telegram_user_id=12345002,
                at=base_time + timedelta(days=3),
                auto_create_user=False,
            )
            self.assertTrue(snapshot.available)
            self.assertEqual(snapshot.plan_code, PLAN_PRO)
            self.assertEqual(snapshot.subscription_status, "active")
            self.assertTrue(snapshot.cancel_at_period_end)
            self.assertTrue(snapshot.payment_failed)

    def test_snapshot_shows_expired_premium_even_with_free_fallback(self):
        base_time = datetime(2026, 8, 1, 7, 0, 0)

        with self.Session() as session:
            seed_default_plans(session)
            user = get_or_create_user(
                session,
                telegram_user_id=12345003,
                username="expired_user",
                now=base_time,
            )
            created = create_subscription(
                session,
                user_id=user.id,
                plan_code=PLAN_PRO,
                started_at=base_time,
                trial_days=0,
                period_days=1,
                now=base_time,
            )
            expire_due_subscriptions(
                session,
                at=base_time + timedelta(days=3),
                commit=True,
            )

            snapshot = get_telegram_subscription_snapshot(
                session,
                telegram_user_id=12345003,
                at=base_time + timedelta(days=3),
            )
            self.assertTrue(snapshot.available)
            self.assertEqual(snapshot.plan_code, PLAN_PRO)
            self.assertEqual(snapshot.subscription_status, "expired")
            self.assertEqual(snapshot.expires_at, created.expires_at)


if __name__ == "__main__":
    unittest.main()

