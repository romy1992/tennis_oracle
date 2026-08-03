"""Admin API for subscriptions dashboard (SUB-06)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.db.session import get_db
from backend.src.app.schemas.subscription_dashboard import (
    SubscriptionDashboardCancelRequest,
    SubscriptionDashboardEventListResponse,
    SubscriptionDashboardManualActionResponse,
    SubscriptionDashboardSummaryResponse,
    SubscriptionDashboardSuspendRequest,
    SubscriptionDashboardUserListResponse,
)
from backend.src.app.services.subscription_dashboard import (
    cancel_subscription_as_admin,
    ensure_subscription_exists,
    export_subscription_dashboard_users_csv,
    get_subscription_dashboard_summary,
    list_subscription_dashboard_events,
    list_subscription_dashboard_users,
    log_admin_action,
    resume_subscription_as_admin,
    suspend_subscription_as_admin,
)
from backend.src.app.services.subscriptions import SubscriptionError
from backend.src.entity.admin_user import AdminUser

router = APIRouter(
    prefix="/subscriptions/dashboard",
    tags=["subscriptions-dashboard"],
    dependencies=[Depends(require_admin)],
)


def _raise_domain(exc: SubscriptionError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/summary", response_model=SubscriptionDashboardSummaryResponse)
def read_dashboard_summary(
    months: int = Query(default=6, ge=1, le=24),
    db: Session = Depends(get_db),
) -> SubscriptionDashboardSummaryResponse:
    try:
        return get_subscription_dashboard_summary(db, months=months)
    except SubscriptionError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc


@router.get("/users", response_model=SubscriptionDashboardUserListResponse)
def read_dashboard_users(
    q: str | None = Query(default=None),
    plan_code: str | None = Query(default=None),
    status: str | None = Query(default=None),
    payment_failed: bool | None = Query(default=None),
    trialing_only: bool = Query(default=False),
    expiring_within_days: int | None = Query(default=None, ge=0, le=365),
    cancel_at_period_end: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SubscriptionDashboardUserListResponse:
    try:
        return list_subscription_dashboard_users(
            db,
            q=q,
            plan_code=plan_code,
            subscription_status=status,
            payment_failed=payment_failed,
            trialing_only=trialing_only,
            expiring_within_days=expiring_within_days,
            cancel_at_period_end=cancel_at_period_end,
            limit=limit,
            offset=offset,
        )
    except SubscriptionError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc


@router.get("/events", response_model=SubscriptionDashboardEventListResponse)
def read_dashboard_events(
    q: str | None = Query(default=None),
    source: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    user_id: int | None = Query(default=None, ge=1),
    subscription_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SubscriptionDashboardEventListResponse:
    try:
        return list_subscription_dashboard_events(
            db,
            q=q,
            source=source,
            event_type=event_type,
            user_id=user_id,
            subscription_id=subscription_id,
            limit=limit,
            offset=offset,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc


@router.get("/export.csv")
def export_dashboard_csv(
    q: str | None = Query(default=None),
    plan_code: str | None = Query(default=None),
    status: str | None = Query(default=None),
    payment_failed: bool | None = Query(default=None),
    trialing_only: bool = Query(default=False),
    expiring_within_days: int | None = Query(default=None, ge=0, le=365),
    cancel_at_period_end: bool | None = Query(default=None),
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    try:
        content, rows_total = export_subscription_dashboard_users_csv(
            db,
            q=q,
            plan_code=plan_code,
            subscription_status=status,
            payment_failed=payment_failed,
            trialing_only=trialing_only,
            expiring_within_days=expiring_within_days,
            cancel_at_period_end=cancel_at_period_end,
        )
        generated_at = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"subscriptions_dashboard_{generated_at}.csv"
        log_admin_action(
            db,
            admin=admin,
            action="subscriptions_export_csv",
            target_type="subscriptions_dashboard",
            target_id="export.csv",
            description=f"CSV export with {rows_total} row(s)",
            context={
                "rows_total": rows_total,
                "filters": {
                    "q": q,
                    "plan_code": plan_code,
                    "status": status,
                    "payment_failed": payment_failed,
                    "trialing_only": trialing_only,
                    "expiring_within_days": expiring_within_days,
                    "cancel_at_period_end": cancel_at_period_end,
                },
            },
            commit=True,
        )
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except SubscriptionError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc


@router.post(
    "/subscriptions/{subscription_id}/suspend",
    response_model=SubscriptionDashboardManualActionResponse,
)
def suspend_dashboard_subscription(
    subscription_id: int,
    payload: SubscriptionDashboardSuspendRequest,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SubscriptionDashboardManualActionResponse:
    try:
        ensure_subscription_exists(subscription_id)
        updated = suspend_subscription_as_admin(
            db,
            admin=admin,
            subscription_id=subscription_id,
            reason=payload.reason,
        )
        return SubscriptionDashboardManualActionResponse(
            message="Abbonamento sospeso.",
            subscription=updated,
        )
    except SubscriptionError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc


@router.post(
    "/subscriptions/{subscription_id}/resume",
    response_model=SubscriptionDashboardManualActionResponse,
)
def resume_dashboard_subscription(
    subscription_id: int,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SubscriptionDashboardManualActionResponse:
    try:
        ensure_subscription_exists(subscription_id)
        updated = resume_subscription_as_admin(
            db,
            admin=admin,
            subscription_id=subscription_id,
        )
        return SubscriptionDashboardManualActionResponse(
            message="Abbonamento riattivato.",
            subscription=updated,
        )
    except SubscriptionError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc


@router.post(
    "/subscriptions/{subscription_id}/cancel",
    response_model=SubscriptionDashboardManualActionResponse,
)
def cancel_dashboard_subscription(
    subscription_id: int,
    payload: SubscriptionDashboardCancelRequest,
    admin: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SubscriptionDashboardManualActionResponse:
    try:
        ensure_subscription_exists(subscription_id)
        updated = cancel_subscription_as_admin(
            db,
            admin=admin,
            subscription_id=subscription_id,
            immediate=payload.immediate,
            reason=payload.reason,
        )
        return SubscriptionDashboardManualActionResponse(
            message="Abbonamento cancellato.",
            subscription=updated,
        )
    except SubscriptionError as exc:
        _raise_domain(exc)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database not available.") from exc

