"""Route tests for payment checkout and Stripe webhook endpoints."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.src.app.main import app
from backend.src.app.schemas.payments import PaymentCheckoutRead, PaymentWebhookAck
from backend.tests.auth_helpers import (
    TEST_SERVICE_API_KEY,
    auth_header_for_admin,
    clear_settings_override,
    create_admin,
    make_test_settings,
    override_settings,
)
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client


class PaymentRoutesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.settings = make_test_settings(
            payments_provider="stripe",
            payments_mode="sandbox",
            payments_success_url="https://example.test/payments/success",
            payments_cancel_url="https://example.test/payments/cancel",
            stripe_price_monthly="price_monthly_test",
            stripe_price_yearly="price_yearly_test",
            stripe_webhook_secret="whsec_test_only",
            service_api_key=TEST_SERVICE_API_KEY,
            allow_unauthenticated_service_reads=False,
        )
        override_settings(self.settings)
        self.client = make_api_client(app, self.Session)

        with self.Session() as session:
            self.admin = create_admin(session, username="admin", password="correct-horse")
            self.admin_headers = auth_header_for_admin(self.admin, self.settings)

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_checkout_requires_auth_or_service_token(self):
        response = self.client.post(
            "/api/payments/checkout",
            json={
                "telegram_user_id": 1001,
                "plan_code": "pro",
                "billing_cycle": "monthly",
                "idempotency_key": "route-idempotency-key-0001",
            },
        )
        self.assertEqual(response.status_code, 401)

    @patch("backend.src.app.api.routes.payments.create_checkout_session_for_telegram_user")
    def test_checkout_accepts_service_token(self, mock_checkout):
        mock_checkout.return_value = PaymentCheckoutRead(
            provider="stripe",
            mode="sandbox",
            idempotency_key="route-idempotency-key-0002",
            checkout_url="https://checkout.stripe.test/route-idempotency-key-0002",
            session_id="cs_test_route",
            customer_id="cus_test_route",
            plan_code="pro",
            billing_cycle="monthly",
            reused=False,
        )

        response = self.client.post(
            "/api/payments/checkout",
            headers={"X-Service-Token": TEST_SERVICE_API_KEY},
            json={
                "telegram_user_id": 1002,
                "username": "route_user",
                "plan_code": "pro",
                "billing_cycle": "monthly",
                "idempotency_key": "route-idempotency-key-0002",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["provider"], "stripe")
        self.assertEqual(payload["session_id"], "cs_test_route")
        mock_checkout.assert_called_once()

    @patch("backend.src.app.api.routes.payments.create_checkout_session_for_telegram_user")
    def test_checkout_accepts_admin_jwt(self, mock_checkout):
        mock_checkout.return_value = PaymentCheckoutRead(
            provider="stripe",
            mode="sandbox",
            idempotency_key="route-idempotency-key-0003",
            checkout_url="https://checkout.stripe.test/route-idempotency-key-0003",
            session_id="cs_test_route_admin",
            customer_id="cus_test_route_admin",
            plan_code="pro",
            billing_cycle="yearly",
            reused=False,
        )

        response = self.client.post(
            "/api/payments/checkout",
            headers=self.admin_headers,
            json={
                "telegram_user_id": 1003,
                "plan_code": "pro",
                "billing_cycle": "yearly",
                "idempotency_key": "route-idempotency-key-0003",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["billing_cycle"], "yearly")
        mock_checkout.assert_called_once()

    @patch("backend.src.app.api.routes.payments.process_stripe_webhook")
    def test_webhook_route_calls_service(self, mock_process_webhook):
        mock_process_webhook.return_value = PaymentWebhookAck(
            processed=True,
            event_id="evt_route_webhook_1",
            event_type="checkout.session.completed",
            duplicate=False,
            message="ok",
        )

        response = self.client.post(
            "/api/payments/webhook/stripe",
            headers={"Stripe-Signature": "t=1,v1=fake"},
            json={"id": "evt_route_webhook_1", "type": "checkout.session.completed"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["processed"])
        self.assertEqual(body["event_id"], "evt_route_webhook_1")
        mock_process_webhook.assert_called_once()


if __name__ == "__main__":
    unittest.main()

