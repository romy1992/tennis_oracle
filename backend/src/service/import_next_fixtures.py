"""
Import upcoming fixtures into next_fixture (rolling snapshot).

Timezone: all date windows use the server local timezone (datetime.now()),
consistent with import_fixtures.calculate_date().
"""
import argparse
import logging
from datetime import date, datetime, timedelta
from typing import Any

from backend.src.entity import Fixture, NextFixture
from backend.src.repository.fixture_repository import FixtureRepository
from backend.src.repository.match_prediction_repository import MatchPredictionRepository
from backend.src.repository.next_fixture_repository import NextFixtureRepository
from backend.src.repository.tournaments_repository import TournamentsRepository
from backend.src.utility.request_api import request_api

fixtures_repo = FixtureRepository()
next_fixtures_repo = NextFixtureRepository()
predictions_repo = MatchPredictionRepository()
tournaments_repo = TournamentsRepository()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COMPLETED_WINNERS = {"First Player", "Second Player"}
FIXTURE_FIELDS = {column.name for column in Fixture.__table__.columns}
NEXT_FIXTURE_API_FIELDS = {
    "event_key",
    "event_date",
    "event_time",
    "event_first_player",
    "first_player_key",
    "event_second_player",
    "second_player_key",
    "tournament_name",
    "tournament_key",
    "tournament_round",
    "event_status",
    "event_type_type",
    "event_final_result",
    "event_game_result",
    "event_serve",
    "event_winner",
    "event_live",
    "event_first_player_logo",
    "event_second_player_logo",
    "event_qualification",
    "tournament_season",
    "pointbypoint",
    "scores",
    "statistics",
}


def today_local() -> date:
    return datetime.now().date()


def iso_week_bounds(event_date: date) -> tuple[date, date]:
    week_start = event_date - timedelta(days=event_date.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def is_singles_match(payload: dict[str, Any]) -> bool:
    event_type = (payload.get("event_type_type") or "").lower()
    return (
        "singles" in event_type
        and "doubles" not in event_type
        and "teams" not in event_type
    )


def is_match_completed(payload: dict[str, Any]) -> bool:
    winner = payload.get("event_winner")
    if winner in COMPLETED_WINNERS:
        return True
    result = payload.get("event_final_result")
    return bool(result and result != "-")


def _surface_for_tournament(tournament_key: int | None) -> str | None:
    if tournament_key is None:
        return None
    tournaments = tournaments_repo.search_filter({"tournament_key": tournament_key})
    if not tournaments:
        return None
    return tournaments[0].tournament_sourface


def _parse_event_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _build_next_fixture(payload: dict[str, Any], odds: dict | None = None) -> NextFixture:
    event_date = _parse_event_date(payload.get("event_date"))
    week_start, week_end = iso_week_bounds(event_date) if event_date else (None, None)
    surface = payload.get("surface") or _surface_for_tournament(payload.get("tournament_key"))

    return NextFixture(
        event_key=payload["event_key"],
        event_date=event_date,
        event_time=payload.get("event_time"),
        event_first_player=payload.get("event_first_player"),
        first_player_key=payload.get("first_player_key"),
        event_second_player=payload.get("event_second_player"),
        second_player_key=payload.get("second_player_key"),
        tournament_name=payload.get("tournament_name"),
        tournament_key=payload.get("tournament_key"),
        tournament_round=payload.get("tournament_round"),
        surface=surface,
        event_status=payload.get("event_status"),
        event_type_type=payload.get("event_type_type"),
        odds=odds,
        imported_at=datetime.now(),
        week_start=week_start,
        week_end=week_end,
        source="api-tennis",
        is_completed=False,
        moved_to_fixture_at=None,
    )


def upsert_next_fixture(payload: dict[str, Any], odds: dict | None = None) -> str:
    existing = next_fixtures_repo.search_filter({"event_key": payload["event_key"]})
    if existing:
        row = existing[0]
        updated = _build_next_fixture(payload, odds=odds or row.odds)
        for column in NextFixture.__table__.columns:
            if column.name in {"id", "is_completed", "moved_to_fixture_at"}:
                continue
            setattr(row, column.name, getattr(updated, column.name))
        next_fixtures_repo.save(row)
        return "updated"

    next_fixtures_repo.save(_build_next_fixture(payload, odds=odds))
    return "inserted"


def upsert_fixture_from_api(payload: dict[str, Any]) -> str:
    fixture_data = {
        key: payload[key]
        for key in FIXTURE_FIELDS
        if key in payload and key != "id_fixture"
    }
    existing = fixtures_repo.search_filter({"event_key": payload["event_key"]})
    if existing:
        row = existing[0]
        for key, value in fixture_data.items():
            setattr(row, key, value)
        fixtures_repo.save(row)
        return "updated"
    fixtures_repo.save(Fixture(**fixture_data))
    return "inserted"


def resolve_predictions_for_match(event_key: int, actual_winner: str | None) -> int:
    if actual_winner not in COMPLETED_WINNERS:
        return 0
    predictions = predictions_repo.search_filter({"event_key": event_key})
    resolved = 0
    for prediction in predictions:
        prediction.actual_winner = actual_winner
        prediction.is_correct = prediction.predicted_winner == actual_winner
        predictions_repo.save(prediction)
        resolved += 1
    return resolved


def promote_completed_match(payload: dict[str, Any]) -> dict[str, int]:
    summary = {"fixtures_inserted": 0, "fixtures_updated": 0, "predictions_resolved": 0}
    if not is_match_completed(payload):
        return summary

    action = upsert_fixture_from_api(payload)
    if action == "inserted":
        summary["fixtures_inserted"] += 1
    else:
        summary["fixtures_updated"] += 1

    summary["predictions_resolved"] += resolve_predictions_for_match(
        payload["event_key"],
        payload.get("event_winner"),
    )

    existing = next_fixtures_repo.search_filter({"event_key": payload["event_key"]})
    if existing:
        row = existing[0]
        row.is_completed = True
        row.moved_to_fixture_at = datetime.now()
        row.event_status = payload.get("event_status", row.event_status)
        next_fixtures_repo.save(row)
    return summary


def fetch_odds_for_match(event_key: int) -> dict | None:
    try:
        odds = request_api(method="get_odds", params={"match_key": event_key})
        return odds if odds else None
    except Exception as exc:
        logger.warning("Odds import failed for event_key=%s: %s", event_key, exc)
        return None


def import_next_fixtures(
    days_forward: int = 10,
    days_back: int = 3,
    import_odds: bool = True,
) -> dict[str, int]:
    """
    Refresh rolling next_fixture snapshot and promote recently completed matches.

    Window: [today, today + days_forward] for upcoming; [today - days_back, today]
    for completion refresh.
    """
    today = today_local()
    date_start = today.strftime("%Y-%m-%d")
    date_stop = (today + timedelta(days=days_forward)).strftime("%Y-%m-%d")

    summary = {
        "inserted": 0,
        "updated": 0,
        "removed_outside_window": 0,
        "removed_completed": 0,
        "promoted_inserted": 0,
        "promoted_updated": 0,
        "predictions_resolved": 0,
        "skipped_non_singles": 0,
    }

    logger.info(
        "Import next fixtures: date_start=%s date_stop=%s (local timezone)",
        date_start,
        date_stop,
    )

    try:
        response = request_api(
            method="get_fixtures",
            params={"date_start": date_start, "date_stop": date_stop},
        )
    except Exception as exc:
        logger.error("get_fixtures failed: %s", exc)
        raise

    if not response:
        logger.info("No fixtures returned for upcoming window.")
    else:
        for payload in response:
            if not is_singles_match(payload):
                summary["skipped_non_singles"] += 1
                continue

            if is_match_completed(payload):
                promoted = promote_completed_match(payload)
                summary["promoted_inserted"] += promoted["fixtures_inserted"]
                summary["promoted_updated"] += promoted["fixtures_updated"]
                summary["predictions_resolved"] += promoted["predictions_resolved"]
                continue

            odds = fetch_odds_for_match(payload["event_key"]) if import_odds else None
            action = upsert_next_fixture(payload, odds=odds)
            summary[action] += 1

    refresh_start = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    refresh_stop = today.strftime("%Y-%m-%d")
    logger.info("Refresh recent matches: %s -> %s", refresh_start, refresh_stop)
    try:
        recent = request_api(
            method="get_fixtures",
            params={"date_start": refresh_start, "date_stop": refresh_stop},
        )
    except Exception as exc:
        logger.warning("Recent fixtures refresh failed: %s", exc)
        recent = []

    for payload in recent or []:
        if not is_singles_match(payload) or not is_match_completed(payload):
            continue
        promoted = promote_completed_match(payload)
        summary["promoted_inserted"] += promoted["fixtures_inserted"]
        summary["promoted_updated"] += promoted["fixtures_updated"]
        summary["predictions_resolved"] += promoted["predictions_resolved"]

    summary["removed_outside_window"] = next_fixtures_repo.delete_outside_date_range(
        from_date=today,
        to_date=today + timedelta(days=days_forward),
    )
    summary["removed_completed"] = next_fixtures_repo.delete_completed()
    logger.info("Import next fixtures summary: %s", summary)
    return summary


def run_daily_next_fixture_import(days_forward: int = 10, days_back: int = 3) -> dict[str, int]:
    return import_next_fixtures(days_forward=days_forward, days_back=days_back)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import upcoming fixtures into next_fixture.")
    parser.add_argument("--days-forward", type=int, default=10)
    parser.add_argument("--days-back", type=int, default=3)
    parser.add_argument("--no-odds", action="store_true")
    args = parser.parse_args()
    run_daily_next_fixture_import(
        days_forward=args.days_forward,
        days_back=args.days_back,
    )
