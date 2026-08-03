"""Unit tests for Stripe payment provider adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

import httpx

from backend.src.app.services.payment_provider import PaymentProviderError, StripePaymentProvider
from backend.tests.auth_helpers import make_test_settings


class StripePaymentProviderTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_test_settings(
            payments_provider="stripe",
            payments_mode="sandbox",
            stripe_secret_key="sk_test_local_123",
            stripe_webhook_secret="whsec_local_123",
            stripe_api_base="https://api.stripe.test/v1",
            stripe_request_timeout_seconds=10.0,
        )
        self.provider = StripePaymentProvider(self.settings)

    def test_parse_webhook_valid_signature(self):
        payload = {
            "id": "evt_test_1",
            "type": "checkout.session.completed",
            "created": 1785585600,
            "data": {"object": {"id": "cs_test_1"}},
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = 1785585600
        signature = hmac.new(
            self.settings.stripe_webhook_secret.encode("utf-8"),
            f"{timestamp}.{body.decode('utf-8')}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        event = self.provider.parse_webhook(
            payload=body,
            signature_header=f"t={timestamp},v1={signature}",
            tolerance_seconds=60 * 60 * 24 * 365,
        )

        self.assertEqual(event.event_id, "evt_test_1")
        self.assertEqual(event.event_type, "checkout.session.completed")
        self.assertEqual(event.object_payload["id"], "cs_test_1")

    def test_parse_webhook_rejects_invalid_signature(self):
        payload = {
            "id": "evt_test_2",
            "type": "checkout.session.completed",
            "created": 1785585600,
            "data": {"object": {}},
        }
        body = json.dumps(payload).encode("utf-8")

        with self.assertRaises(PaymentProviderError) as ctx:
            self.provider.parse_webhook(
                payload=body,
                signature_header="t=1785585600,v1=definitely_wrong",
                tolerance_seconds=60 * 60 * 24 * 365,
            )

        self.assertEqual(ctx.exception.status_code, 400)

    @patch("backend.src.app.services.payment_provider.httpx.post")
    def test_create_customer_calls_stripe_api(self, mock_post):
        mock_post.return_value = httpx.Response(200, json={"id": "cus_mocked_1"})

        customer = self.provider.create_customer(
            external_user_id="42",
            telegram_user_id=555,
            username="alice",
            email=None,
            metadata={"plan_code": "pro"},
        )

        self.assertEqual(customer.customer_id, "cus_mocked_1")
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["url"], "https://api.stripe.test/v1/customers")
        self.assertEqual(kwargs["data"]["name"], "alice")
        self.assertEqual(kwargs["data"]["metadata[app_user_id]"], "42")
        self.assertEqual(kwargs["data"]["metadata[telegram_user_id]"], "555")

    @patch("backend.src.app.services.payment_provider.httpx.post")
    def test_create_customer_portal_session_calls_stripe_api(self, mock_post):
        mock_post.return_value = httpx.Response(
            200,
            json={
                "id": "bps_mocked_1",
                "url": "https://billing.stripe.test/session_1",
                "created": 1785585600,
            },
        )

        portal = self.provider.create_customer_portal_session(
            external_user_id="42",
            customer_id="cus_mocked_1",
            return_url="https://example.test/account",
            idempotency_key="portal-idem-123",
        )

        self.assertEqual(portal.session_id, "bps_mocked_1")
        self.assertEqual(portal.portal_url, "https://billing.stripe.test/session_1")
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["url"], "https://api.stripe.test/v1/billing_portal/sessions")
        self.assertEqual(kwargs["data"]["customer"], "cus_mocked_1")
        self.assertEqual(kwargs["data"]["return_url"], "https://example.test/account")
        self.assertEqual(kwargs["headers"]["Idempotency-Key"], "portal-idem-123")

    def test_create_checkout_rejects_live_key_in_sandbox(self):
        invalid = make_test_settings(
            payments_provider="stripe",
            payments_mode="sandbox",
            stripe_secret_key="sk_live_prod_should_not_be_used_here",
            stripe_webhook_secret="whsec_local_123",
            stripe_api_base="https://api.stripe.test/v1",
        )
        provider = StripePaymentProvider(invalid)

        with self.assertRaises(PaymentProviderError) as ctx:
            provider.create_checkout_session(
                external_user_id="42",
                customer_id="cus_1",
                price_id="price_1",
                success_url="https://example.test/success",
                cancel_url="https://example.test/cancel",
                metadata={"app_user_id": "42"},
                idempotency_key="idem-12345678",
            )

        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()



