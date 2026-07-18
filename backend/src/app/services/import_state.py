import json
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.src.app.models import Fixture, NextFixture
from backend.src.app.services.predictions import UPCOMING_DAYS_FORWARD


STATE_PATH = Path(__file__).resolve().parents[3] / "data" / "import_state.json"


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def record_fixture_import(
    *,
    last_match_date: date | None,
    imported_at: datetime | None = None,
    days_back_start: int | None = None,
) -> None:
    state = _load_state()
    state["fixtures"] = {
        "last_match_date": last_match_date.isoformat() if last_match_date else None,
        "imported_at": (imported_at or datetime.now()).isoformat(),
        "days_back_start": days_back_start,
    }
    _save_state(state)


def get_fixture_import_state() -> dict:
    return _load_state().get("fixtures", {})


def get_import_status(db: Session) -> dict:
    today = date.today()
    next_last_imported_at = db.scalar(select(func.max(NextFixture.imported_at)))
    next_fixtures_max_date = db.scalar(
        select(func.max(NextFixture.event_date)).where(NextFixture.is_completed.is_(False))
    )
    # Cap to today so future contamination in fixture never drives the status panel.
    fixtures_last_match_date = db.scalar(
        select(func.max(Fixture.event_date)).where(Fixture.event_date <= today)
    )
    fixture_state = get_fixture_import_state()

    next_imported_today = (
        next_last_imported_at.date() == today if next_last_imported_at is not None else False
    )
    next_fixtures_window_until = today + timedelta(days=UPCOMING_DAYS_FORWARD)

    fixtures_last_imported_at_raw = fixture_state.get("imported_at")
    fixtures_last_imported_at = (
        datetime.fromisoformat(fixtures_last_imported_at_raw)
        if fixtures_last_imported_at_raw
        else None
    )
    fixtures_last_imported_match_date_raw = fixture_state.get("last_match_date")
    fixtures_last_imported_match_date = (
        date.fromisoformat(fixtures_last_imported_match_date_raw)
        if fixtures_last_imported_match_date_raw
        else None
    )
    if fixtures_last_imported_match_date is not None and fixtures_last_imported_match_date > today:
        # Stale JSON from an unbounded max(event_date); prefer live DB.
        fixtures_last_imported_match_date = fixtures_last_match_date
    elif fixtures_last_imported_match_date is None:
        fixtures_last_imported_match_date = fixtures_last_match_date

    return {
        "next_fixtures_last_imported_at": next_last_imported_at,
        "next_fixtures_imported_today": next_imported_today,
        "next_fixtures_max_date": next_fixtures_max_date,
        "next_fixtures_window_days": UPCOMING_DAYS_FORWARD,
        "next_fixtures_window_until": next_fixtures_window_until,
        "fixtures_last_match_date": fixtures_last_imported_match_date,
        "fixtures_last_imported_at": fixtures_last_imported_at,
    }
