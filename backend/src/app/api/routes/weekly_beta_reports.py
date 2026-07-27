"""Admin weekly beta report API."""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.src.app.api.deps import require_admin
from backend.src.app.core.config import get_settings
from backend.src.app.db.session import get_db
from backend.src.app.schemas.weekly_beta_report import (
    WeeklyBetaReportGenerateRequest,
    WeeklyBetaReportGenerateResponse,
    WeeklyBetaReportListResponse,
    WeeklyBetaReportRead,
)
from backend.src.app.services.weekly_beta_report import (
    generate_and_store_weekly_beta_report,
    get_latest_weekly_beta_report,
    get_weekly_beta_report,
    list_weekly_beta_reports,
    report_to_list_item,
    report_to_read,
)

router = APIRouter(
    prefix="/weekly-beta-reports",
    tags=["weekly-beta-reports"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=WeeklyBetaReportListResponse)
def list_reports(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> WeeklyBetaReportListResponse:
    rows, total = list_weekly_beta_reports(db, limit=limit, offset=offset)
    return WeeklyBetaReportListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[report_to_list_item(row) for row in rows],
    )


@router.get("/latest", response_model=WeeklyBetaReportRead)
def read_latest_report(db: Session = Depends(get_db)) -> WeeklyBetaReportRead:
    row = get_latest_weekly_beta_report(db)
    if row is None:
        raise HTTPException(status_code=404, detail="Nessun report settimanale disponibile")
    return report_to_read(row)


@router.post("/generate", response_model=WeeklyBetaReportGenerateResponse)
def generate_report(
    body: WeeklyBetaReportGenerateRequest = Body(default_factory=WeeklyBetaReportGenerateRequest),
    db: Session = Depends(get_db),
) -> WeeklyBetaReportGenerateResponse:
    """Compute (or refresh) a weekly report and optionally notify admin on Telegram."""
    try:
        row, created, telegram = generate_and_store_weekly_beta_report(
            db,
            week_start=body.week_start,
            settings=get_settings(),
            send_telegram=body.send_telegram,
            force=body.force,
            generated_by="admin_api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return WeeklyBetaReportGenerateResponse(
        report=report_to_read(row),
        created=created,
        telegram=telegram,
    )


@router.get("/{report_id}", response_model=WeeklyBetaReportRead)
def read_report(report_id: int, db: Session = Depends(get_db)) -> WeeklyBetaReportRead:
    row = get_weekly_beta_report(db, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report non trovato")
    return report_to_read(row)
