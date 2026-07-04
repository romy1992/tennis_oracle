from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.src.app.ml.model_versioning import ModelVersion
from backend.src.app.models import Fixture
from backend.src.app.services.import_state import get_import_status, record_fixture_import
from backend.src.jobs.generate_upcoming_predictions import run_upcoming_prediction_generation
from backend.src.service.import_fixtures import run_daily_fixture_import
from backend.src.service.import_next_fixtures import run_daily_next_fixture_import


def refresh_matches(
    db: Session,
    *,
    days_forward: int = 10,
    days_back_next: int = 3,
    model_version: ModelVersion = "v2",
    model_name: str | None = None,
    force_next_import: bool = False,
) -> dict:
    status_before = get_import_status(db)
    next_fixtures_imported = False
    next_fixtures_summary = None

    if force_next_import or not status_before["next_fixtures_imported_today"]:
        next_fixtures_summary = run_daily_next_fixture_import(
            days_forward=days_forward,
            days_back=days_back_next,
        )
        next_fixtures_imported = True

    predictions_summary = run_upcoming_prediction_generation(
        days_forward=days_forward,
        model_version=model_version,
        model_name=model_name,
    )

    fixtures_summary = import_played_fixtures(db, days_back=max(days_back_next, 1))

    return {
        "next_fixtures_imported": next_fixtures_imported,
        "next_fixtures_summary": next_fixtures_summary,
        "predictions_summary": predictions_summary,
        "fixtures_summary": fixtures_summary,
        "import_status": get_import_status(db),
    }


def import_played_fixtures(
    db: Session,
    *,
    days_back: int = 1,
) -> dict:
    if days_back < 0:
        raise ValueError("days_back must be >= 0")

    run_daily_fixture_import(days_back_start=days_back, days_back_stop=0)

    date_from = date.today() - timedelta(days=days_back)
    last_match_date = db.scalar(
        select(func.max(Fixture.event_date)).where(Fixture.event_date >= date_from)
    )
    record_fixture_import(
        last_match_date=last_match_date,
        imported_at=datetime.now(),
        days_back_start=days_back,
    )

    return {
        "days_back": days_back,
        "import_status": get_import_status(db),
    }
