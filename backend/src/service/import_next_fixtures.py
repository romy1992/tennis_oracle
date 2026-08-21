"""
Import upcoming fixtures into next_fixture (rolling snapshot).

Timezone: all date windows use the server local timezone (datetime.now()),
consistent with import_fixtures.calculate_date().
"""
import argparse
import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.entity import Fixture, MatchPrediction, NextFixture
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
# api-tennis.com rejects get_fixtures windows wider than 7 days
# (returns result="Maximum date range for odds is 7 days.").
API_FIXTURES_MAX_RANGE_DAYS = 7
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


def is_singles_match(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    event_type = (payload.get("event_type_type") or "").lower()
    return (
        "singles" in event_type
        and "doubles" not in event_type
        and "teams" not in event_type
    )


def _normalize_fixtures_response(raw: Any, context: str) -> list[dict[str, Any]]:
    """Best-effort normalization for upstream API shape drift."""
    if raw is None:
        return []

    if isinstance(raw, str):
        raise RuntimeError(f"API Tennis error for {context}: {raw}")

    if isinstance(raw, dict):
        nested = raw.get("result") or raw.get("results") or raw.get("data") or []
        if isinstance(nested, str):
            raise RuntimeError(f"API Tennis error for {context}: {nested}")
        raw = nested

    if not isinstance(raw, list):
        logger.warning("Unexpected fixtures response type for %s: %s", context, type(raw).__name__)
        return []

    normalized: list[dict[str, Any]] = []
    skipped = 0
    for item in raw:
        if isinstance(item, dict):
            normalized.append(item)
        else:
            skipped += 1

    if skipped:
        logger.warning("Skipped %s non-dict fixture payload(s) for %s", skipped, context)
    return normalized


def iter_date_chunks(start: date, end: date, max_span_days: int = API_FIXTURES_MAX_RANGE_DAYS):
    """Yield inclusive (chunk_start, chunk_end) spans of at most max_span_days."""
    if end < start:
        return
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=max_span_days), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def is_match_completed(payload: dict[str, Any]) -> bool:
    """Promote only when API provides a bettable winner.

    Cancelled/postponed/abandoned matches may carry odd ``event_final_result``
    values; those must stay in ``next_fixture`` with their ``event_status`` so
    settlement can void picks on-read without inventing a winner.
    """
    return payload.get("event_winner") in COMPLETED_WINNERS


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


def _parse_event_time(value: Any) -> time | None:
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def _fixture_data_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    fixture_data = {
        key: payload[key]
        for key in FIXTURE_FIELDS
        if key in payload and key != "id_fixture"
    }
    if "event_date" in fixture_data:
        fixture_data["event_date"] = _parse_event_date(fixture_data["event_date"])
    if "event_time" in fixture_data:
        fixture_data["event_time"] = _parse_event_time(fixture_data["event_time"])
    return fixture_data


def normalized_live_score(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Build the single rolling score snapshot stored on ``NextFixture``.

    API-Tennis exposes these fields both from ``get_fixtures`` and
    ``get_livescore``. Empty pre-match placeholders are stored as ``None`` so
    consumers do not mistake them for a live score.
    """
    scores = payload.get("scores")
    current_game = payload.get("event_game_result")
    server = payload.get("event_serve")
    final_result = payload.get("event_final_result")
    status = payload.get("event_status")

    has_sets = isinstance(scores, list) and bool(scores)
    has_game = current_game not in (None, "", "-", "0 - 0")
    has_final = final_result not in (None, "", "-", "0 - 0")
    has_server = server not in (None, "", "-")
    if not any((has_sets, has_game, has_final, has_server)):
        return None
    return {
        "sets": scores if isinstance(scores, list) else [],
        "current_game": current_game,
        "server": server,
        "final_result": final_result,
        "status": status,
    }


def _build_next_fixture(payload: dict[str, Any], odds: dict | None = None) -> NextFixture:
    event_date = _parse_event_date(payload.get("event_date"))
    week_start, week_end = iso_week_bounds(event_date) if event_date else (None, None)
    surface = payload.get("surface") or _surface_for_tournament(payload.get("tournament_key"))

    live_score = normalized_live_score(payload)
    return NextFixture(
        event_key=payload["event_key"],
        event_date=event_date,
        event_time=_parse_event_time(payload.get("event_time")),
        event_first_player=payload.get("event_first_player"),
        first_player_key=payload.get("first_player_key"),
        event_second_player=payload.get("event_second_player"),
        second_player_key=payload.get("second_player_key"),
        tournament_name=payload.get("tournament_name"),
        tournament_key=payload.get("tournament_key"),
        tournament_round=payload.get("tournament_round"),
        surface=surface,
        event_status=payload.get("event_status"),
        event_winner=payload.get("event_winner"),
        event_live=payload.get("event_live"),
        event_type_type=payload.get("event_type_type"),
        live_score=live_score,
        live_score_updated_at=datetime.now() if live_score is not None else None,
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
        stored_odds = odds or row.odds
        updated = _build_next_fixture(payload, odds=stored_odds)
        if updated.live_score is None:
            updated.live_score = row.live_score
            updated.live_score_updated_at = row.live_score_updated_at
        for column in NextFixture.__table__.columns:
            if column.name in {"id", "is_completed", "moved_to_fixture_at"}:
                continue
            setattr(row, column.name, getattr(updated, column.name))
        next_fixtures_repo.save(row)
        if odds:
            _capture_prematch_odds_history(payload, odds)
        return "updated"

    next_fixtures_repo.save(_build_next_fixture(payload, odds=odds))
    if odds:
        _capture_prematch_odds_history(payload, odds)
    return "inserted"


def _capture_prematch_odds_history(payload: dict[str, Any], odds: dict) -> None:
    """Append-only history; failures must not break next_fixture import."""
    from backend.src.app.services.prematch_odds_snapshots import capture_imported_odds

    capture_imported_odds(
        event_key=int(payload["event_key"]),
        odds=odds,
        player_1_name=payload.get("event_first_player"),
        player_2_name=payload.get("event_second_player"),
        event_live=payload.get("event_live"),
        source="import",
    )


def upsert_fixture_from_api(payload: dict[str, Any]) -> str:
    fixture_data = _fixture_data_from_payload(payload)
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


def promote_completed_match(
    payload: dict[str, Any],
    *,
    db: Session | None = None,
) -> dict[str, int]:
    summary = {"fixtures_inserted": 0, "fixtures_updated": 0, "predictions_resolved": 0}
    if not is_match_completed(payload):
        return summary

    if db is not None:
        fixture_data = _fixture_data_from_payload(payload)
        fixture = db.scalar(
            select(Fixture).where(Fixture.event_key == int(payload["event_key"]))
        )
        if fixture is None:
            db.add(Fixture(**fixture_data))
            summary["fixtures_inserted"] = 1
        else:
            for key, value in fixture_data.items():
                setattr(fixture, key, value)
            summary["fixtures_updated"] = 1

        actual_winner = payload.get("event_winner")
        if actual_winner in COMPLETED_WINNERS:
            predictions = db.scalars(
                select(MatchPrediction).where(
                    MatchPrediction.event_key == int(payload["event_key"])
                )
            ).all()
            for prediction in predictions:
                prediction.actual_winner = actual_winner
                prediction.is_correct = prediction.predicted_winner == actual_winner
            summary["predictions_resolved"] = len(predictions)

        next_fixture = db.scalar(
            select(NextFixture).where(
                NextFixture.event_key == int(payload["event_key"])
            )
        )
        if next_fixture is not None:
            next_fixture.is_completed = True
            next_fixture.moved_to_fixture_at = datetime.now()
            next_fixture.event_status = payload.get(
                "event_status", next_fixture.event_status
            )
            next_fixture.event_winner = payload.get(
                "event_winner", next_fixture.event_winner
            )
            next_fixture.event_live = payload.get(
                "event_live", next_fixture.event_live
            )
            score = normalized_live_score(payload)
            if score is not None:
                next_fixture.live_score = score
                next_fixture.live_score_updated_at = datetime.now()
        db.flush()
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
        row.event_winner = payload.get(
            "event_winner", getattr(row, "event_winner", None)
        )
        row.event_live = payload.get("event_live", getattr(row, "event_live", None))
        score = normalized_live_score(payload)
        if score is not None:
            row.live_score = score
            row.live_score_updated_at = datetime.now()
        next_fixtures_repo.save(row)
    return summary


def fetch_odds_for_match(event_key: int) -> dict | None:
    try:
        odds = request_api(method="get_odds", params={"match_key": event_key})
        return odds if odds else None
    except Exception as exc:
        logger.warning("Odds import failed for event_key=%s: %s", event_key, exc)
        return None


def _ingest_upcoming_payloads(
    payloads: list[dict[str, Any]],
    summary: dict[str, int],
    *,
    import_odds: bool,
) -> None:
    for payload in payloads:
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


def import_next_fixtures(
    days_forward: int = 10,
    days_back: int = 3,
    import_odds: bool = True,
) -> dict[str, int]:
    """
    Refresh rolling next_fixture snapshot and promote recently completed matches.

    Window: [today, today + days_forward] for upcoming; [today - days_back, today]
    for completion refresh.

    Upcoming fetches are chunked to respect the API max range (7 days).
    Cleanup runs only after a successful upcoming fetch so a failed API call
    cannot wipe an existing calendar.
    """
    today = today_local()
    window_end = today + timedelta(days=days_forward)

    summary = {
        "inserted": 0,
        "updated": 0,
        "removed_outside_window": 0,
        "removed_completed": 0,
        "promoted_inserted": 0,
        "promoted_updated": 0,
        "predictions_resolved": 0,
        "skipped_non_singles": 0,
        "api_chunks": 0,
    }

    logger.info(
        "Import next fixtures: date_start=%s date_stop=%s (local timezone)",
        today.isoformat(),
        window_end.isoformat(),
    )

    upcoming_ok = False
    try:
        for chunk_start, chunk_end in iter_date_chunks(today, window_end):
            summary["api_chunks"] += 1
            response = request_api(
                method="get_fixtures",
                params={
                    "date_start": chunk_start.strftime("%Y-%m-%d"),
                    "date_stop": chunk_end.strftime("%Y-%m-%d"),
                },
            )
            response_items = _normalize_fixtures_response(
                response,
                context=f"upcoming_window[{chunk_start}..{chunk_end}]",
            )
            if not response_items:
                logger.info(
                    "No fixtures returned for upcoming chunk %s -> %s",
                    chunk_start,
                    chunk_end,
                )
            else:
                _ingest_upcoming_payloads(
                    response_items,
                    summary,
                    import_odds=import_odds,
                )
        upcoming_ok = True
    except Exception as exc:
        logger.error("get_fixtures failed: %s", exc)
        raise

    refresh_start = today - timedelta(days=days_back)
    logger.info("Refresh recent matches: %s -> %s", refresh_start, today)
    try:
        for chunk_start, chunk_end in iter_date_chunks(refresh_start, today):
            recent = request_api(
                method="get_fixtures",
                params={
                    "date_start": chunk_start.strftime("%Y-%m-%d"),
                    "date_stop": chunk_end.strftime("%Y-%m-%d"),
                },
            )
            recent_items = _normalize_fixtures_response(
                recent,
                context=f"recent_window[{chunk_start}..{chunk_end}]",
            )
            for payload in recent_items:
                if not is_singles_match(payload) or not is_match_completed(payload):
                    continue
                promoted = promote_completed_match(payload)
                summary["promoted_inserted"] += promoted["fixtures_inserted"]
                summary["promoted_updated"] += promoted["fixtures_updated"]
                summary["predictions_resolved"] += promoted["predictions_resolved"]
    except Exception as exc:
        logger.warning("Recent fixtures refresh failed: %s", exc)

    if upcoming_ok:
        summary["removed_outside_window"] = next_fixtures_repo.delete_outside_date_range(
            from_date=today,
            to_date=window_end,
        )
        summary["removed_completed"] = next_fixtures_repo.delete_completed()
    else:
        logger.warning("Skipping next_fixture cleanup because upcoming fetch did not complete.")

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
