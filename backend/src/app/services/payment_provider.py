"""Provider-agnostic payment interface plus Stripe implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from backend.src.app.core.config import Settings

logger = logging.getLogger(__name__)


class PaymentProviderError(Exception):
    """Provider-level error mapped to API-safe status codes."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        code: str = "provider_error",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderCustomer:
    provider: str
    customer_id: str
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class ProviderCheckoutSession:
    provider: str
    session_id: str
    checkout_url: str
    expires_at: datetime | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class ProviderCustomerPortalSession:
    provider: str
    session_id: str
    portal_url: str
    created_at: datetime | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class ProviderWebhookEvent:
    provider: str
    event_id: str
    event_type: str
    created_at: datetime
    object_payload: dict[str, Any]
    raw_payload: dict[str, Any]


class PaymentProvider(ABC):
    """Abstract provider contract used by payment orchestration."""

    provider_name: str

    @abstractmethod
    def create_customer(
        self,
        *,
        external_user_id: str,
        telegram_user_id: int | None,
        username: str | None,
        email: str | None,
        metadata: dict[str, str],
    ) -> ProviderCustomer:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def create_customer_portal_session(
        self,
        *,
        external_user_id: str,
        customer_id: str,
        return_url: str,
        idempotency_key: str | None,
    ) -> ProviderCustomerPortalSession:
        raise NotImplementedError

    @abstractmethod
    def parse_webhook(
        self,
        *,
        payload: bytes,
        signature_header: str | None,
        tolerance_seconds: int,
    ) -> ProviderWebhookEvent:
        raise NotImplementedError


class StripePaymentProvider(PaymentProvider):
    provider_name = "stripe"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_base = (settings.stripe_api_base or "https://api.stripe.com/v1").rstrip("/")
        self._mode = (settings.payments_mode or "sandbox").strip().lower()

    def create_customer(
        self,
        *,
        external_user_id: str,
        telegram_user_id: int | None,
        username: str | None,
        email: str | None,
        metadata: dict[str, str],
    ) -> ProviderCustomer:
        data: dict[str, str] = {}
        if username:
            data["name"] = username
        if email:
            data["email"] = email

        all_metadata = dict(metadata)
        all_metadata.setdefault("app_user_id", external_user_id)
        if telegram_user_id is not None:
            all_metadata.setdefault("telegram_user_id", str(telegram_user_id))
        for key, value in all_metadata.items():
            cleaned_key = str(key).strip()
            cleaned_value = str(value).strip()
            if cleaned_key and cleaned_value:
                data[f"metadata[{cleaned_key}]"] = cleaned_value

        payload = self._post_form("/customers", data=data, idempotency_key=None)
        customer_id = _clean_text(payload.get("id"))
        if customer_id is None:
            raise PaymentProviderError(
                "Stripe non ha restituito un customer id valido.",
                status_code=502,
                code="invalid_provider_response",
            )
        return ProviderCustomer(
            provider=self.provider_name,
            customer_id=customer_id,
            raw_payload=payload,
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
        if not success_url or not cancel_url:
            raise PaymentProviderError(
                "Success/cancel URL mancanti per la checkout session.",
                status_code=500,
                code="missing_checkout_urls",
            )

        data: dict[str, str] = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": external_user_id,
        }
        for key, value in metadata.items():
            cleaned_key = str(key).strip()
            cleaned_value = str(value).strip()
            if cleaned_key and cleaned_value:
                data[f"metadata[{cleaned_key}]"] = cleaned_value

        payload = self._post_form(
            "/checkout/sessions",
            data=data,
            idempotency_key=idempotency_key,
        )
        session_id = _clean_text(payload.get("id"))
        checkout_url = _clean_text(payload.get("url"))
        if session_id is None or checkout_url is None:
            raise PaymentProviderError(
                "Stripe non ha restituito i campi minimi della checkout session.",
                status_code=502,
                code="invalid_provider_response",
            )

        return ProviderCheckoutSession(
            provider=self.provider_name,
            session_id=session_id,
            checkout_url=checkout_url,
            expires_at=_epoch_to_naive_utc(payload.get("expires_at")),
            raw_payload=payload,
        )

    def create_customer_portal_session(
        self,
        *,
        external_user_id: str,
        customer_id: str,
        return_url: str,
        idempotency_key: str | None,
    ) -> ProviderCustomerPortalSession:
        del external_user_id  # Reserved for providers that support explicit external refs.
        if not return_url:
            raise PaymentProviderError(
                "Return URL mancante per il portale cliente.",
                status_code=500,
                code="missing_portal_return_url",
            )

        payload = self._post_form(
            "/billing_portal/sessions",
            data={
                "customer": customer_id,
                "return_url": return_url,
            },
            idempotency_key=idempotency_key,
        )
        session_id = _clean_text(payload.get("id"))
        portal_url = _clean_text(payload.get("url"))
        if session_id is None or portal_url is None:
            raise PaymentProviderError(
                "Stripe non ha restituito i campi minimi del portale cliente.",
                status_code=502,
                code="invalid_provider_response",
            )

        return ProviderCustomerPortalSession(
            provider=self.provider_name,
            session_id=session_id,
            portal_url=portal_url,
            created_at=_epoch_to_naive_utc(payload.get("created")),
            raw_payload=payload,
        )

    def parse_webhook(
        self,
        *,
        payload: bytes,
        signature_header: str | None,
        tolerance_seconds: int,
    ) -> ProviderWebhookEvent:
        secret = self._webhook_secret_key()
        timestamp, signatures = _parse_stripe_signature_header(signature_header)

        now_ts = int(datetime.now(timezone.utc).timestamp())
        if tolerance_seconds > 0 and abs(now_ts - timestamp) > tolerance_seconds:
            raise PaymentProviderError(
                "Stripe webhook fuori tolleranza temporale.",
                status_code=400,
                code="webhook_timestamp_out_of_tolerance",
            )

        try:
            body_text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PaymentProviderError(
                "Payload webhook Stripe non UTF-8.",
                status_code=400,
                code="invalid_webhook_payload",
            ) from exc

        signed_payload = f"{timestamp}.{body_text}".encode("utf-8")
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        is_valid = any(hmac.compare_digest(expected, candidate) for candidate in signatures)
        if not is_valid:
            raise PaymentProviderError(
                "Firma webhook Stripe non valida.",
                status_code=400,
                code="invalid_webhook_signature",
            )

        try:
            event_payload = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise PaymentProviderError(
                "Payload webhook Stripe non JSON valido.",
                status_code=400,
                code="invalid_webhook_payload",
            ) from exc

        if not isinstance(event_payload, dict):
            raise PaymentProviderError(
                "Payload webhook Stripe inatteso.",
                status_code=400,
                code="invalid_webhook_payload",
            )

        event_id = _clean_text(event_payload.get("id"))
        event_type = _clean_text(event_payload.get("type"))
        if event_id is None or event_type is None:
            raise PaymentProviderError(
                "Webhook Stripe senza id/type.",
                status_code=400,
                code="invalid_webhook_payload",
            )

        data_section = event_payload.get("data")
        object_payload: dict[str, Any] = {}
        if isinstance(data_section, dict) and isinstance(data_section.get("object"), dict):
            object_payload = data_section["object"]

        created_at = _epoch_to_naive_utc(event_payload.get("created"))
        if created_at is None:
            created_at = datetime.now(timezone.utc).replace(tzinfo=None)

        return ProviderWebhookEvent(
            provider=self.provider_name,
            event_id=event_id,
            event_type=event_type,
            created_at=created_at,
            object_payload=object_payload,
            raw_payload=event_payload,
        )

    def _secret_key(self) -> str:
        key = (self._settings.stripe_secret_key or "").strip()
        if not key:
            raise PaymentProviderError(
                "Stripe secret key non configurata.",
                status_code=503,
                code="missing_provider_configuration",
            )
        if self._mode == "sandbox" and key.startswith("sk_live_"):
            raise PaymentProviderError(
                "Stripe live key usata in modalita sandbox.",
                status_code=503,
                code="invalid_provider_configuration",
            )
        if self._mode == "live" and key.startswith("sk_test_"):
            raise PaymentProviderError(
                "Stripe test key usata in modalita live.",
                status_code=503,
                code="invalid_provider_configuration",
            )
        return key

    def _webhook_secret_key(self) -> str:
        secret = (self._settings.stripe_webhook_secret or "").strip()
        if not secret:
            raise PaymentProviderError(
                "Stripe webhook secret non configurato.",
                status_code=503,
                code="missing_provider_configuration",
            )
        return secret

    def _post_form(
        self,
        path: str,
        *,
        data: dict[str, str],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        url = f"{self._api_base}{path}"
        headers = {"Authorization": f"Bearer {self._secret_key()}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        timeout = max(1.0, float(self._settings.stripe_request_timeout_seconds))
        try:
            response = httpx.post(url=url, data=data, headers=headers, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise PaymentProviderError(
                "Timeout chiamata Stripe.",
                status_code=504,
                code="provider_timeout",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise PaymentProviderError(
                "Errore rete verso Stripe.",
                status_code=502,
                code="provider_network_error",
                retryable=True,
            ) from exc

        payload = _response_json_dict(response)
        if response.status_code >= 400:
            message = _extract_stripe_error_message(payload) or "Errore Stripe non specificato."
            status_code = 400 if 400 <= response.status_code < 500 else 503
            retryable = response.status_code in {408, 429} or response.status_code >= 500
            raise PaymentProviderError(
                message,
                status_code=status_code,
                code="provider_http_error",
                retryable=retryable,
            )
        return payload


def _parse_stripe_signature_header(signature_header: str | None) -> tuple[int, list[str]]:
    if not signature_header:
        raise PaymentProviderError(
            "Header Stripe-Signature mancante.",
            status_code=400,
            code="missing_webhook_signature",
        )

    timestamp: int | None = None
    signatures: list[str] = []
    for chunk in signature_header.split(","):
        piece = chunk.strip()
        if not piece or "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError as exc:
                raise PaymentProviderError(
                    "Timestamp Stripe-Signature non valido.",
                    status_code=400,
                    code="invalid_webhook_signature",
                ) from exc
        elif key == "v1" and value:
            signatures.append(value)

    if timestamp is None or not signatures:
        raise PaymentProviderError(
            "Formato Stripe-Signature non valido.",
            status_code=400,
            code="invalid_webhook_signature",
        )
    return timestamp, signatures


def _response_json_dict(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _extract_stripe_error_message(payload: dict[str, Any]) -> str | None:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = _clean_text(error.get("message"))
        if message:
            return message
    return _clean_text(payload.get("message"))


def _epoch_to_naive_utc(value: Any) -> datetime | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return cleaned



