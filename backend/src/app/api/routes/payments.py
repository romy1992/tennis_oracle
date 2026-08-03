"""Payment routes (provider-agnostic orchestration + Stripe webhook)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin_or_service
from backend.src.app.db.session import get_db
from backend.src.app.schemas.payments import (
    PaymentCheckoutCreate,
    PaymentCheckoutRead,
    PaymentWebhookAck,
)
from backend.src.app.services.payments import (
    PaymentServiceError,
    create_checkout_session_for_telegram_user,
    process_stripe_webhook,
)


router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "/checkout",
    response_model=PaymentCheckoutRead,
    dependencies=[Depends(require_admin_or_service)],
)
def create_checkout_session(
    payload: PaymentCheckoutCreate,
    db: Session = Depends(get_db),
) -> PaymentCheckoutRead:
    try:
        return create_checkout_session_for_telegram_user(
            db,
            telegram_user_id=payload.telegram_user_id,
            username=payload.username,
            plan_code=payload.plan_code,
            billing_cycle=payload.billing_cycle,
            success_url=str(payload.success_url) if payload.success_url else None,
            cancel_url=str(payload.cancel_url) if payload.cancel_url else None,
            idempotency_key=payload.idempotency_key,
        )
    except PaymentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc


@router.post("/webhook/stripe", response_model=PaymentWebhookAck)
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> PaymentWebhookAck:
    signature = request.headers.get("Stripe-Signature")
    payload = await request.body()
    try:
        return process_stripe_webhook(
            db,
            payload=payload,
            signature_header=signature,
        )
    except PaymentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc

