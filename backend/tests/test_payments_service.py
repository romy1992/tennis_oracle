"""Tests for provider-agnostic payments orchestration and Stripe webhook flow."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from backend.src.app.services.payment_provider import (
    PaymentProvider,
    ProviderCheckoutSession,
    ProviderCustomer,
    ProviderCustomerPortalSession,
    ProviderWebhookEvent,
)
from backend.src.app.services.payments import (
    PaymentServiceError,
    create_checkout_session_for_telegram_user,
    create_customer_portal_session_for_telegram_user,
    process_stripe_webhook,
)
from backend.src.entity.subscription import PaymentCheckoutSession, PaymentCustomer, PaymentEvent, Subscription
from backend.tests.auth_helpers import clear_settings_override, make_test_settings, override_settings
from backend.tests.db_helpers import create_session_factory, create_test_engine


class FakeStripeProvider(PaymentProvider):
    provider_name = "stripe"

    def __init__(self):
        self.customer_calls = 0
        self.checkout_calls = 0
        self.portal_calls = 0
        self.next_webhook_event: ProviderWebhookEvent | None = None

    def create_customer(
        self,
        *,
        external_user_id: str,
        telegram_user_id: int | None,
        username: str | None,
        email: str | None,
        metadata: dict[str, str],
    ) -> ProviderCustomer:
        self.customer_calls += 1
        return ProviderCustomer(
            provider=self.provider_name,
            customer_id=f"cus_test_{external_user_id}",
            raw_payload={"id": f"cus_test_{external_user_id}", "metadata": metadata},
        )

    def create_checkout_session(
        self,
        *,
        external_user_id: str,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> ProviderCheckoutSession:
        self.checkout_calls += 1
        return ProviderCheckoutSession(
            provider=self.provider_name,
            session_id=f"cs_test_{idempotency_key[-12:]}",
            checkout_url=f"https://checkout.stripe.test/{idempotency_key}",
            expires_at=datetime(2026, 8, 1, 12, 45, 0),
            raw_payload={
                "id": f"cs_test_{idempotency_key[-12:]}",
                "url": f"https://checkout.stripe.test/{idempotency_key}",
                "customer": customer_id,
                "price": price_id,
                "metadata": metadata,
            },
        )

    def create_customer_portal_session(
        self,
        *,
        external_user_id: str,
        customer_id: str,
        return_url: str,
        idempotency_key: str | None,
    ) -> ProviderCustomerPortalSession:
        self.portal_calls += 1
        suffix = (idempotency_key or "portal")[0:12]
        return ProviderCustomerPortalSession(
            provider=self.provider_name,
            session_id=f"bps_test_{suffix}",
            portal_url=f"https://billing.stripe.test/{customer_id}/{suffix}",
            created_at=datetime(2026, 8, 1, 12, 0, 0),
            raw_payload={
                "id": f"bps_test_{suffix}",
                "url": f"https://billing.stripe.test/{customer_id}/{suffix}",
                "customer": customer_id,
                "return_url": return_url,
                "external_user_id": external_user_id,
            },
        )

    def parse_webhook(
        self,
        *,
        payload: bytes,
        signature_header: str | None,
        tolerance_seconds: int,
    ) -> ProviderWebhookEvent:
        if self.next_webhook_event is None:
            raise AssertionError("next_webhook_event non impostato nel fake provider")
        return self.next_webhook_event


class PaymentsServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.settings = make_test_settings(
            payments_provider="stripe",
            payments_mode="sandbox",
            payments_success_url="https://example.test/payments/success",
            payments_cancel_url="https://example.test/payments/cancel",
            payments_portal_return_url="https://example.test/account",
            payments_portal_link_ttl_seconds=600,
            payments_idempotency_bucket_seconds=900,
            stripe_price_monthly="price_monthly_test",
            stripe_price_yearly="price_yearly_test",
            stripe_webhook_tolerance_seconds=300,
        )
        override_settings(self.settings)
        self.provider = FakeStripeProvider()

    def tearDown(self):
        clear_settings_override()
        self.engine.dispose()

    def _create_paid_subscription_via_checkout_webhook(
        self,
        session,
        *,
        telegram_user_id: int,
        username: str,
        idempotency_key: str,
        checkout_event_id: str,
        provider_subscription_id: str,
        created_at: datetime,
    ):
        checkout = create_checkout_session_for_telegram_user(
            session,
            telegram_user_id=telegram_user_id,
            username=username,
            plan_code="pro",
            billing_cycle="monthly",
            success_url=None,
            cancel_url=None,
            idempotency_key=idempotency_key,
            settings=self.settings,
            provider_override=self.provider,
            now=created_at,
        )

        checkout_row = session.execute(
            select(PaymentCheckoutSession).where(PaymentCheckoutSession.idempotency_key == idempotency_key)
        ).scalar_one()

        completed_payload: dict[str, Any] = {
            "id": checkout_event_id,
            "type": "checkout.session.completed",
            "created": int(created_at.timestamp()),
            "data": {
                "object": {
                    "id": checkout.session_id,
                    "customer": checkout.customer_id,
                    "subscription": provider_subscription_id,
                    "amount_total": 1900,
                    "currency": "EUR",
                    "metadata": {
                        "app_user_id": str(checkout_row.user_id),
                        "plan_code": "pro",
                        "billing_cycle": "monthly",
                    },
                }
            },
        }
        self.provider.next_webhook_event = ProviderWebhookEvent(
            provider="stripe",
            event_id=checkout_event_id,
            event_type="checkout.session.completed",
            created_at=created_at,
            object_payload=completed_payload["data"]["object"],
            raw_payload=completed_payload,
        )
        ack = process_stripe_webhook(
            session,
            payload=b"{}",
            signature_header="t=0,v1=fake",
            settings=self.settings,
            provider_override=self.provider,
        )
        self.assertTrue(ack.processed)

        subscription = session.scalars(
            select(Subscription)
            .where(Subscription.user_id == checkout_row.user_id)
            .order_by(Subscription.id.desc())
        ).first()
        self.assertIsNotNone(subscription)
        assert subscription is not None
        return checkout, checkout_row, subscription

    def test_checkout_is_idempotent_for_same_key(self):
        now = datetime(2026, 8, 1, 12, 0, 0)
        idem_key = "checkout-idem-key-0001"

        with self.Session() as session:
            first = create_checkout_session_for_telegram_user(
                session,
                telegram_user_id=123456,
                username="alice",
                plan_code="pro",
                billing_cycle="monthly",
                success_url=None,
                cancel_url=None,
                idempotency_key=idem_key,
                settings=self.settings,
                provider_override=self.provider,
                now=now,
            )
            second = create_checkout_session_for_telegram_user(
                session,
                telegram_user_id=123456,
                username="alice",
                plan_code="pro",
                billing_cycle="monthly",
                success_url=None,
                cancel_url=None,
                idempotency_key=idem_key,
                settings=self.settings,
                provider_override=self.provider,
                now=now,
            )

            self.assertEqual(first.session_id, second.session_id)
            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
            self.assertEqual(self.provider.customer_calls, 1)
            self.assertEqual(self.provider.checkout_calls, 1)

            customer_count = int(session.scalar(select(func.count()).select_from(PaymentCustomer)) or 0)
            checkout_count = int(session.scalar(select(func.count()).select_from(PaymentCheckoutSession)) or 0)
            self.assertEqual(customer_count, 1)
            self.assertEqual(checkout_count, 1)

    def test_customer_portal_link_is_created_for_existing_customer(self):
        now = datetime(2026, 8, 2, 9, 0, 0)

        with self.Session() as session:
            create_checkout_session_for_telegram_user(
                session,
                telegram_user_id=111001,
                username="portal_user",
                plan_code="pro",
                billing_cycle="monthly",
                success_url=None,
                cancel_url=None,
                idempotency_key="checkout-idem-key-portal-1",
                settings=self.settings,
                provider_override=self.provider,
                now=now,
            )

            portal = create_customer_portal_session_for_telegram_user(
                session,
                telegram_user_id=111001,
                username="portal_user",
                return_url=None,
                idempotency_key=None,
                settings=self.settings,
                provider_override=self.provider,
                now=now,
            )

            self.assertEqual(portal.provider, "stripe")
            self.assertIn("https://billing.stripe.test/", portal.portal_url)
            self.assertIsNotNone(portal.expires_at)
            assert portal.expires_at is not None
            self.assertEqual(portal.expires_at, now + timedelta(seconds=600))
            self.assertEqual(self.provider.portal_calls, 1)

    def test_customer_portal_requires_customer_mapping(self):
        now = datetime(2026, 8, 2, 10, 0, 0)

        with self.Session() as session:
            with self.assertRaises(PaymentServiceError) as ctx:
                create_customer_portal_session_for_telegram_user(
                    session,
                    telegram_user_id=111002,
                    username="no_customer",
                    return_url=None,
                    idempotency_key=None,
                    settings=self.settings,
                    provider_override=self.provider,
                    now=now,
                )
            self.assertEqual(ctx.exception.status_code, 404)

    def test_yearly_checkout_requires_configured_yearly_price(self):
        no_yearly_settings = make_test_settings(
            payments_provider="stripe",
            payments_mode="sandbox",
            payments_success_url="https://example.test/payments/success",
            payments_cancel_url="https://example.test/payments/cancel",
            stripe_price_monthly="price_monthly_test",
            stripe_price_yearly=None,
        )

        with self.Session() as session:
            with self.assertRaises(PaymentServiceError) as ctx:
                create_checkout_session_for_telegram_user(
                    session,
                    telegram_user_id=777,
                    username="bob",
                    plan_code="pro",
                    billing_cycle="yearly",
                    success_url=None,
                    cancel_url=None,
                    idempotency_key="checkout-idem-key-0002",
                    settings=no_yearly_settings,
                    provider_override=self.provider,
                    now=datetime(2026, 8, 1, 13, 0, 0),
                )
            self.assertEqual(ctx.exception.status_code, 400)

    def test_checkout_webhook_creates_subscription_and_deduplicates(self):
        created_at = datetime(2026, 8, 1, 14, 0, 0)

        with self.Session() as session:
            checkout = create_checkout_session_for_telegram_user(
                session,
                telegram_user_id=999001,
                username="carol",
                plan_code="pro",
                billing_cycle="monthly",
                success_url=None,
                cancel_url=None,
                idempotency_key="checkout-idem-key-0003",
                settings=self.settings,
                provider_override=self.provider,
                now=created_at,
            )

            checkout_row = session.execute(
                select(PaymentCheckoutSession).where(
                    PaymentCheckoutSession.idempotency_key == "checkout-idem-key-0003"
                )
            ).scalar_one()

            event_payload: dict[str, Any] = {
                "id": "evt_checkout_completed_1",
                "type": "checkout.session.completed",
                "created": int(created_at.timestamp()),
                "data": {
                    "object": {
                        "id": checkout.session_id,
                        "customer": checkout.customer_id,
                        "subscription": "sub_test_1",
                        "amount_total": 1900,
                        "currency": "EUR",
                        "payment_method_details": {
                            "card": {
                                "brand": "visa",
                                "last4": "4242",
                                "fingerprint": "fp_123",
                            }
                        },
                        "metadata": {
                            "app_user_id": str(checkout_row.user_id),
                            "plan_code": "pro",
                            "billing_cycle": "monthly",
                        },
                    }
                },
            }
            self.provider.next_webhook_event = ProviderWebhookEvent(
                provider="stripe",
                event_id="evt_checkout_completed_1",
                event_type="checkout.session.completed",
                created_at=created_at,
                object_payload=event_payload["data"]["object"],
                raw_payload=event_payload,
            )

            first_ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )
            second_ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )

            self.assertTrue(first_ack.processed)
            self.assertFalse(second_ack.processed)
            self.assertTrue(second_ack.duplicate)

            subscriptions = session.scalars(
                select(Subscription)
                .where(Subscription.user_id == checkout_row.user_id)
                .order_by(Subscription.id.asc())
            ).all()
            self.assertEqual(len(subscriptions), 1)
            self.assertEqual(subscriptions[0].status, "active")

            provider_event_count = int(
                session.scalar(
                    select(func.count()).select_from(PaymentEvent).where(
                        PaymentEvent.provider == "stripe",
                        PaymentEvent.provider_event_id == "evt_checkout_completed_1",
                    )
                )
                or 0
            )
            self.assertEqual(provider_event_count, 1)

            payment_event = session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider == "stripe",
                    PaymentEvent.provider_event_id == "evt_checkout_completed_1",
                )
            )
            self.assertIsNotNone(payment_event)
            assert payment_event is not None
            self.assertIsNotNone(payment_event.raw_payload_json)
            raw_payload = payment_event.raw_payload_json or ""
            self.assertNotIn("payment_method_details", raw_payload)
            self.assertNotIn("fingerprint", raw_payload)

            refreshed_checkout = session.scalar(
                select(PaymentCheckoutSession).where(PaymentCheckoutSession.id == checkout_row.id)
            )
            self.assertIsNotNone(refreshed_checkout)
            assert refreshed_checkout is not None
            self.assertEqual(refreshed_checkout.status, "completed")
            self.assertEqual(refreshed_checkout.provider_subscription_id, "sub_test_1")

    def test_invoice_cycle_webhook_renews_subscription(self):
        base_time = datetime(2026, 8, 1, 15, 0, 0)

        with self.Session() as session:
            checkout = create_checkout_session_for_telegram_user(
                session,
                telegram_user_id=999002,
                username="dave",
                plan_code="pro",
                billing_cycle="monthly",
                success_url=None,
                cancel_url=None,
                idempotency_key="checkout-idem-key-0004",
                settings=self.settings,
                provider_override=self.provider,
                now=base_time,
            )

            checkout_row = session.execute(
                select(PaymentCheckoutSession).where(
                    PaymentCheckoutSession.idempotency_key == "checkout-idem-key-0004"
                )
            ).scalar_one()

            completed_payload: dict[str, Any] = {
                "id": "evt_checkout_completed_2",
                "type": "checkout.session.completed",
                "created": int(base_time.timestamp()),
                "data": {
                    "object": {
                        "id": checkout.session_id,
                        "customer": checkout.customer_id,
                        "subscription": "sub_test_2",
                        "amount_total": 1900,
                        "currency": "EUR",
                        "metadata": {
                            "app_user_id": str(checkout_row.user_id),
                            "plan_code": "pro",
                            "billing_cycle": "monthly",
                        },
                    }
                },
            }
            self.provider.next_webhook_event = ProviderWebhookEvent(
                provider="stripe",
                event_id="evt_checkout_completed_2",
                event_type="checkout.session.completed",
                created_at=base_time,
                object_payload=completed_payload["data"]["object"],
                raw_payload=completed_payload,
            )
            process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )

            before_renew = session.scalars(
                select(Subscription)
                .where(Subscription.user_id == checkout_row.user_id)
                .order_by(Subscription.id.desc())
            ).first()
            self.assertIsNotNone(before_renew)
            assert before_renew is not None
            initial_expiry = before_renew.expires_at
            self.assertIsNotNone(initial_expiry)

            cycle_start = int((base_time + timedelta(days=30)).timestamp())
            cycle_end = int((base_time + timedelta(days=60)).timestamp())
            invoice_payload: dict[str, Any] = {
                "id": "evt_invoice_cycle_1",
                "type": "invoice.payment_succeeded",
                "created": int((base_time + timedelta(days=30)).timestamp()),
                "data": {
                    "object": {
                        "id": "in_test_1",
                        "customer": checkout.customer_id,
                        "billing_reason": "subscription_cycle",
                        "amount_paid": 1900,
                        "currency": "EUR",
                        "lines": {
                            "data": [
                                {
                                    "period": {
                                        "start": cycle_start,
                                        "end": cycle_end,
                                    }
                                }
                            ]
                        },
                    }
                },
            }
            self.provider.next_webhook_event = ProviderWebhookEvent(
                provider="stripe",
                event_id="evt_invoice_cycle_1",
                event_type="invoice.payment_succeeded",
                created_at=base_time + timedelta(days=30),
                object_payload=invoice_payload["data"]["object"],
                raw_payload=invoice_payload,
            )

            ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )
            self.assertTrue(ack.processed)

            after_renew = session.scalars(
                select(Subscription)
                .where(Subscription.user_id == checkout_row.user_id)
                .order_by(Subscription.id.desc())
            ).first()
            self.assertIsNotNone(after_renew)
            assert after_renew is not None
            self.assertIsNotNone(after_renew.expires_at)
            assert initial_expiry is not None
            assert after_renew.expires_at is not None
            self.assertGreater(after_renew.expires_at, initial_expiry)

            renewal_events = int(
                session.scalar(
                    select(func.count()).select_from(PaymentEvent).where(
                        PaymentEvent.provider == "stripe",
                        PaymentEvent.provider_event_id == "evt_invoice_cycle_1",
                    )
                )
                or 0
            )
            self.assertEqual(renewal_events, 1)

    def test_subscription_updated_webhook_updates_subscription_flags(self):
        base_time = datetime(2026, 8, 1, 16, 0, 0)

        with self.Session() as session:
            checkout, checkout_row, subscription = self._create_paid_subscription_via_checkout_webhook(
                session,
                telegram_user_id=999003,
                username="erin",
                idempotency_key="checkout-idem-key-0005",
                checkout_event_id="evt_checkout_completed_3",
                provider_subscription_id="sub_test_3",
                created_at=base_time,
            )

            period_start = int((base_time + timedelta(days=30)).timestamp())
            period_end = int((base_time + timedelta(days=60)).timestamp())
            updated_at = base_time + timedelta(days=10)
            updated_payload: dict[str, Any] = {
                "id": "evt_subscription_updated_1",
                "type": "customer.subscription.updated",
                "created": int(updated_at.timestamp()),
                "data": {
                    "object": {
                        "id": "sub_test_3",
                        "customer": checkout.customer_id,
                        "status": "active",
                        "cancel_at_period_end": True,
                        "current_period_start": period_start,
                        "current_period_end": period_end,
                    }
                },
            }
            self.provider.next_webhook_event = ProviderWebhookEvent(
                provider="stripe",
                event_id="evt_subscription_updated_1",
                event_type="customer.subscription.updated",
                created_at=updated_at,
                object_payload=updated_payload["data"]["object"],
                raw_payload=updated_payload,
            )

            ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )
            self.assertTrue(ack.processed)

            refreshed = session.scalar(select(Subscription).where(Subscription.id == subscription.id))
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            self.assertEqual(refreshed.status, "active")
            self.assertTrue(refreshed.cancel_at_period_end)
            self.assertFalse(refreshed.auto_renew)
            self.assertEqual(
                refreshed.current_period_end_at,
                datetime.fromtimestamp(period_end, tz=timezone.utc).replace(tzinfo=None),
            )

            refreshed_checkout = session.scalar(
                select(PaymentCheckoutSession).where(PaymentCheckoutSession.id == checkout_row.id)
            )
            self.assertIsNotNone(refreshed_checkout)
            assert refreshed_checkout is not None
            self.assertEqual(refreshed_checkout.provider_subscription_id, "sub_test_3")

            updated_event = session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider == "stripe",
                    PaymentEvent.provider_event_id == "evt_subscription_updated_1",
                )
            )
            self.assertIsNotNone(updated_event)
            assert updated_event is not None
            self.assertEqual(updated_event.event_type, "subscription_updated")

    def test_subscription_updated_webhook_is_idempotent(self):
        base_time = datetime(2026, 8, 1, 16, 30, 0)

        with self.Session() as session:
            checkout, _, _ = self._create_paid_subscription_via_checkout_webhook(
                session,
                telegram_user_id=999008,
                username="jane",
                idempotency_key="checkout-idem-key-0010",
                checkout_event_id="evt_checkout_completed_8",
                provider_subscription_id="sub_test_8",
                created_at=base_time,
            )

            updated_payload: dict[str, Any] = {
                "id": "evt_subscription_updated_dup_1",
                "type": "customer.subscription.updated",
                "created": int((base_time + timedelta(days=1)).timestamp()),
                "data": {
                    "object": {
                        "id": "sub_test_8",
                        "customer": checkout.customer_id,
                        "status": "active",
                        "cancel_at_period_end": False,
                    }
                },
            }
            self.provider.next_webhook_event = ProviderWebhookEvent(
                provider="stripe",
                event_id="evt_subscription_updated_dup_1",
                event_type="customer.subscription.updated",
                created_at=base_time + timedelta(days=1),
                object_payload=updated_payload["data"]["object"],
                raw_payload=updated_payload,
            )

            first_ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )
            second_ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )

            self.assertTrue(first_ack.processed)
            self.assertFalse(second_ack.processed)
            self.assertTrue(second_ack.duplicate)

            dedup_count = int(
                session.scalar(
                    select(func.count()).select_from(PaymentEvent).where(
                        PaymentEvent.provider == "stripe",
                        PaymentEvent.provider_event_id == "evt_subscription_updated_dup_1",
                    )
                )
                or 0
            )
            self.assertEqual(dedup_count, 1)

    def test_invoice_payment_failed_webhook_records_failed_event(self):
        base_time = datetime(2026, 8, 1, 17, 0, 0)

        with self.Session() as session:
            checkout, _, subscription = self._create_paid_subscription_via_checkout_webhook(
                session,
                telegram_user_id=999004,
                username="frank",
                idempotency_key="checkout-idem-key-0006",
                checkout_event_id="evt_checkout_completed_4",
                provider_subscription_id="sub_test_4",
                created_at=base_time,
            )

            failed_payload: dict[str, Any] = {
                "id": "evt_invoice_failed_1",
                "type": "invoice.payment_failed",
                "created": int((base_time + timedelta(days=31)).timestamp()),
                "data": {
                    "object": {
                        "id": "in_failed_1",
                        "customer": checkout.customer_id,
                        "amount_due": 1900,
                        "currency": "EUR",
                    }
                },
            }
            self.provider.next_webhook_event = ProviderWebhookEvent(
                provider="stripe",
                event_id="evt_invoice_failed_1",
                event_type="invoice.payment_failed",
                created_at=base_time + timedelta(days=31),
                object_payload=failed_payload["data"]["object"],
                raw_payload=failed_payload,
            )

            ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )
            self.assertTrue(ack.processed)

            failed_event = session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider == "stripe",
                    PaymentEvent.provider_event_id == "evt_invoice_failed_1",
                )
            )
            self.assertIsNotNone(failed_event)
            assert failed_event is not None
            self.assertEqual(failed_event.event_type, "invoice_payment_failed")
            self.assertEqual(failed_event.status, "failed")
            self.assertEqual(failed_event.amount_cents, 1900)

            refreshed = session.scalar(select(Subscription).where(Subscription.id == subscription.id))
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            self.assertEqual(refreshed.status, "active")

    def test_subscription_deleted_webhook_cancels_subscription(self):
        base_time = datetime(2026, 8, 1, 18, 0, 0)

        with self.Session() as session:
            checkout, checkout_row, subscription = self._create_paid_subscription_via_checkout_webhook(
                session,
                telegram_user_id=999005,
                username="gina",
                idempotency_key="checkout-idem-key-0007",
                checkout_event_id="evt_checkout_completed_5",
                provider_subscription_id="sub_test_5",
                created_at=base_time,
            )

            deleted_payload: dict[str, Any] = {
                "id": "evt_subscription_deleted_1",
                "type": "customer.subscription.deleted",
                "created": int((base_time + timedelta(days=5)).timestamp()),
                "data": {
                    "object": {
                        "id": "sub_test_5",
                        "customer": checkout.customer_id,
                        "currency": "EUR",
                    }
                },
            }
            self.provider.next_webhook_event = ProviderWebhookEvent(
                provider="stripe",
                event_id="evt_subscription_deleted_1",
                event_type="customer.subscription.deleted",
                created_at=base_time + timedelta(days=5),
                object_payload=deleted_payload["data"]["object"],
                raw_payload=deleted_payload,
            )

            ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )
            self.assertTrue(ack.processed)

            refreshed = session.scalar(select(Subscription).where(Subscription.id == subscription.id))
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            self.assertEqual(refreshed.status, "canceled")

            refreshed_checkout = session.scalar(
                select(PaymentCheckoutSession).where(PaymentCheckoutSession.id == checkout_row.id)
            )
            self.assertIsNotNone(refreshed_checkout)
            assert refreshed_checkout is not None
            self.assertEqual(refreshed_checkout.status, "canceled")

    def test_charge_refunded_webhook_records_refund_event(self):
        base_time = datetime(2026, 8, 1, 19, 0, 0)

        with self.Session() as session:
            checkout, _, _ = self._create_paid_subscription_via_checkout_webhook(
                session,
                telegram_user_id=999006,
                username="hank",
                idempotency_key="checkout-idem-key-0008",
                checkout_event_id="evt_checkout_completed_6",
                provider_subscription_id="sub_test_6",
                created_at=base_time,
            )

            refunded_payload: dict[str, Any] = {
                "id": "evt_charge_refunded_1",
                "type": "charge.refunded",
                "created": int((base_time + timedelta(days=2)).timestamp()),
                "data": {
                    "object": {
                        "id": "ch_test_1",
                        "customer": checkout.customer_id,
                        "status": "succeeded",
                        "amount_refunded": 1900,
                        "currency": "EUR",
                        "reason": "requested_by_customer",
                    }
                },
            }
            self.provider.next_webhook_event = ProviderWebhookEvent(
                provider="stripe",
                event_id="evt_charge_refunded_1",
                event_type="charge.refunded",
                created_at=base_time + timedelta(days=2),
                object_payload=refunded_payload["data"]["object"],
                raw_payload=refunded_payload,
            )

            ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )
            self.assertTrue(ack.processed)

            refund_event = session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider == "stripe",
                    PaymentEvent.provider_event_id == "evt_charge_refunded_1",
                )
            )
            self.assertIsNotNone(refund_event)
            assert refund_event is not None
            self.assertEqual(refund_event.event_type, "charge_refunded")
            self.assertEqual(refund_event.status, "succeeded")
            self.assertEqual(refund_event.amount_cents, 1900)

    def test_charge_dispute_created_and_closed_won_webhooks_suspend_then_resume(self):
        base_time = datetime(2026, 8, 1, 20, 0, 0)

        with self.Session() as session:
            checkout, _, subscription = self._create_paid_subscription_via_checkout_webhook(
                session,
                telegram_user_id=999007,
                username="iris",
                idempotency_key="checkout-idem-key-0009",
                checkout_event_id="evt_checkout_completed_7",
                provider_subscription_id="sub_test_7",
                created_at=base_time,
            )

            created_payload: dict[str, Any] = {
                "id": "evt_dispute_created_1",
                "type": "charge.dispute.created",
                "created": int((base_time + timedelta(days=3)).timestamp()),
                "data": {
                    "object": {
                        "id": "dp_test_1",
                        "customer": checkout.customer_id,
                        "status": "needs_response",
                        "reason": "fraudulent",
                        "amount": 1900,
                        "currency": "EUR",
                    }
                },
            }
            self.provider.next_webhook_event = ProviderWebhookEvent(
                provider="stripe",
                event_id="evt_dispute_created_1",
                event_type="charge.dispute.created",
                created_at=base_time + timedelta(days=3),
                object_payload=created_payload["data"]["object"],
                raw_payload=created_payload,
            )
            created_ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )
            self.assertTrue(created_ack.processed)

            suspended = session.scalar(select(Subscription).where(Subscription.id == subscription.id))
            self.assertIsNotNone(suspended)
            assert suspended is not None
            self.assertEqual(suspended.status, "suspended")

            closed_payload: dict[str, Any] = {
                "id": "evt_dispute_closed_1",
                "type": "charge.dispute.closed",
                "created": int((base_time + timedelta(days=4)).timestamp()),
                "data": {
                    "object": {
                        "id": "dp_test_1",
                        "customer": checkout.customer_id,
                        "status": "won",
                        "amount": 1900,
                        "currency": "EUR",
                    }
                },
            }
            self.provider.next_webhook_event = ProviderWebhookEvent(
                provider="stripe",
                event_id="evt_dispute_closed_1",
                event_type="charge.dispute.closed",
                created_at=base_time + timedelta(days=4),
                object_payload=closed_payload["data"]["object"],
                raw_payload=closed_payload,
            )
            closed_ack = process_stripe_webhook(
                session,
                payload=b"{}",
                signature_header="t=0,v1=fake",
                settings=self.settings,
                provider_override=self.provider,
            )
            self.assertTrue(closed_ack.processed)

            resumed = session.scalar(select(Subscription).where(Subscription.id == subscription.id))
            self.assertIsNotNone(resumed)
            assert resumed is not None
            self.assertEqual(resumed.status, "active")
            self.assertIsNone(resumed.suspension_reason)

            closed_event = session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider == "stripe",
                    PaymentEvent.provider_event_id == "evt_dispute_closed_1",
                )
            )
            self.assertIsNotNone(closed_event)
            assert closed_event is not None
            self.assertEqual(closed_event.event_type, "charge_dispute_closed")
            self.assertEqual(closed_event.status, "succeeded")


if __name__ == "__main__":
    unittest.main()






