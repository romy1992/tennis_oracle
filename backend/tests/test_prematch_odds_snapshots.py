"""Tests for the append-only pre-match odds snapshot ledger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from sqlalchemy import select

from backend.src.app.schemas.prematch_odds_snapshot import (
    PrematchOddsSnapshotCreate,
    PrematchOddsSnapshotFromPayload,
)
from backend.src.app.services.prematch_odds_snapshots import (
    PrematchOddsSnapshotError,
    capture_closing_odds_for_fixture,
    compute_detection_hash,
    find_fixtures_pending_closing_capture,
    get_snapshot,
    list_snapshots,
    record_odds_from_stored_fixture,
    record_odds_payload,
    record_snapshot,
    run_closing_odds_capture_once,
)
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot


SAMPLE_ODDS = {
    "Home/Away": {
        "Home": {"Bet365": "1.80", "Pinnacle": "1.85"},
        "Away": {"Bet365": "2.10", "Pinnacle": "2.05"},
    }
}


def _seed_next_fixture(db_session, *, event_key: int = 5010, odds=None) -> NextFixture:
    row = NextFixture(
        event_key=event_key,
        event_date=datetime.utcnow().date() + timedelta(days=1),
        event_time=None,
        event_first_player="Alice",
        event_second_player="Bob",
        tournament_name="Test Open",
        event_status="Not Started",
        odds=odds if odds is not None else SAMPLE_ODDS,
        is_completed=False,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_record_payload_creates_opening_snapshots(db_session):
    result = record_odds_payload(
        db_session,
        PrematchOddsSnapshotFromPayload(
            event_key=5010,
            odds=SAMPLE_ODDS,
            source="import",
            snapshot_type="auto",
            player_1_name="Alice",
            player_2_name="Bob",
        ),
    )

    # 2 bookmakers × 2 selections
    assert result.inserted == 4
    assert result.skipped_duplicates == 0
    assert all(item.snapshot_type == "opening" for item in result.items)
    assert {item.selection for item in result.items} == {"Alice", "Bob"}
    alice = next(item for item in result.items if item.selection == "Alice" and item.bookmaker == "Bet365")
    assert alice.odds == pytest.approx(1.8)
    assert alice.implied_probability == pytest.approx(1.0 / 1.8)
    assert alice.margin == pytest.approx((1.0 / 1.8) + (1.0 / 2.1) - 1.0)
    assert alice.market_side == "Home"


def test_unchanged_odds_are_not_duplicated(db_session):
    first = record_odds_payload(
        db_session,
        PrematchOddsSnapshotFromPayload(
            event_key=5011,
            odds=SAMPLE_ODDS,
            source="import",
            player_1_name="Alice",
            player_2_name="Bob",
        ),
    )
    second = record_odds_payload(
        db_session,
        PrematchOddsSnapshotFromPayload(
            event_key=5011,
            odds=SAMPLE_ODDS,
            source="import",
            player_1_name="Alice",
            player_2_name="Bob",
        ),
    )

    assert first.inserted == 4
    assert second.inserted == 0
    assert second.skipped_duplicates == 4
    stored = list(
        db_session.scalars(
            select(PrematchOddsSnapshot).where(PrematchOddsSnapshot.event_key == 5011)
        ).all()
    )
    assert len(stored) == 4


def test_changed_odds_append_observed_without_overwrite(db_session):
    record_odds_payload(
        db_session,
        PrematchOddsSnapshotFromPayload(
            event_key=5012,
            odds=SAMPLE_ODDS,
            source="import",
            player_1_name="Alice",
            player_2_name="Bob",
        ),
    )
    moved = {
        "Home/Away": {
            "Home": {"Bet365": "1.90", "Pinnacle": "1.85"},
            "Away": {"Bet365": "2.00", "Pinnacle": "2.05"},
        }
    }
    second = record_odds_payload(
        db_session,
        PrematchOddsSnapshotFromPayload(
            event_key=5012,
            odds=moved,
            source="import",
            player_1_name="Alice",
            player_2_name="Bob",
        ),
    )

    # Only Bet365 sides changed
    assert second.inserted == 2
    assert all(item.snapshot_type == "observed" for item in second.items)

    history = list_snapshots(db_session, event_key=5012, bookmaker="Bet365", selection="Alice")
    assert history.total == 2
    odds_values = [item.odds for item in history.items]
    assert 1.8 in odds_values
    assert 1.9 in odds_values
    opening = db_session.scalar(
        select(PrematchOddsSnapshot).where(
            PrematchOddsSnapshot.event_key == 5012,
            PrematchOddsSnapshot.bookmaker == "Bet365",
            PrematchOddsSnapshot.selection == "Alice",
            PrematchOddsSnapshot.snapshot_type == "opening",
        )
    )
    assert opening is not None
    assert opening.odds == pytest.approx(1.8)


def test_detection_hash_stable():
    when = datetime(2026, 7, 22, 12, 0, 0)
    kwargs = dict(
        event_key=1,
        selection="Alice",
        bookmaker="Bet365",
        odds=1.85,
        snapshot_type="observed",
        source="import",
        captured_at=when,
    )
    assert compute_detection_hash(**kwargs) == compute_detection_hash(**kwargs)


def test_publication_and_closing_types(db_session):
    created = record_snapshot(
        db_session,
        PrematchOddsSnapshotCreate(
            event_key=5013,
            selection="Alice",
            bookmaker="Bet365",
            odds=1.75,
            margin=0.05,
            source="publication",
            snapshot_type="publication",
        ),
    )
    assert created is not None
    assert created.snapshot_type == "publication"

    closing = record_snapshot(
        db_session,
        PrematchOddsSnapshotCreate(
            event_key=5013,
            selection="Alice",
            bookmaker="Bet365",
            odds=1.75,
            margin=0.05,
            source="system",
            snapshot_type="closing",
            captured_at=datetime(2026, 7, 22, 14, 0, 0),
        ),
    )
    assert closing is not None
    assert closing.snapshot_type == "closing"

    # Same detection (same second) is skipped
    again = record_snapshot(
        db_session,
        PrematchOddsSnapshotCreate(
            event_key=5013,
            selection="Alice",
            bookmaker="Bet365",
            odds=1.75,
            margin=0.05,
            source="system",
            snapshot_type="closing",
            captured_at=datetime(2026, 7, 22, 14, 0, 0),
        ),
    )
    assert again is None


def test_record_from_stored_fixture(db_session):
    _seed_next_fixture(db_session, event_key=5014)
    result = record_odds_from_stored_fixture(db_session, 5014, source="admin_api")
    assert result.inserted == 4
    detail = get_snapshot(db_session, result.items[0].id)
    assert detail.event_key == 5014


def test_missing_fixture_raises(db_session):
    with pytest.raises(PrematchOddsSnapshotError) as exc:
        record_odds_from_stored_fixture(db_session, 99999)
    assert exc.value.status_code == 404


def test_api_ingest_and_list(client, auth_headers, db_session):
    _seed_next_fixture(db_session, event_key=5020)

    create_resp = client.post(
        "/api/prematch-odds-snapshots/from-fixture/5020",
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["inserted"] == 4

    listed = client.get(
        "/api/prematch-odds-snapshots",
        params={"event_key": 5020},
        headers=auth_headers,
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 4

    payload_resp = client.post(
        "/api/prematch-odds-snapshots/from-payload",
        headers=auth_headers,
        json={
            "event_key": 5021,
            "odds": SAMPLE_ODDS,
            "source": "admin_api",
            "snapshot_type": "auto",
            "player_1_name": "Alice",
            "player_2_name": "Bob",
        },
    )
    assert payload_resp.status_code == 201
    assert payload_resp.json()["inserted"] == 4

    single = client.post(
        "/api/prematch-odds-snapshots",
        headers=auth_headers,
        json={
            "event_key": 5021,
            "selection": "Alice",
            "bookmaker": "Bet365",
            "odds": 1.95,
            "margin": 0.04,
            "source": "manual",
            "snapshot_type": "observed",
        },
    )
    assert single.status_code == 201
    snapshot_id = single.json()["id"]

    detail = client.get(
        f"/api/prematch-odds-snapshots/{snapshot_id}",
        headers=auth_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["odds"] == pytest.approx(1.95)

    # Unchanged detection → 409
    dup = client.post(
        "/api/prematch-odds-snapshots",
        headers=auth_headers,
        json={
            "event_key": 5021,
            "selection": "Alice",
            "bookmaker": "Bet365",
            "odds": 1.95,
            "margin": 0.04,
            "source": "manual",
            "snapshot_type": "observed",
        },
    )
    assert dup.status_code == 409


# ---------------------------------------------------------------------------
# Dedicated pre-kickoff closing-odds capture (find_fixtures_pending_closing_capture,
# capture_closing_odds_for_fixture, run_closing_odds_capture_once).
# ---------------------------------------------------------------------------


def _seed_fixture_with_kickoff(
    db_session,
    *,
    event_key: int,
    minutes_from_now: float,
    is_completed: bool = False,
) -> NextFixture:
    """Seed a NextFixture whose Rome-local event_date/event_time round-trips
    (via the service's Rome->UTC conversion) back to ``minutes_from_now`` from
    the current naive-UTC instant."""
    from zoneinfo import ZoneInfo

    kickoff_utc = datetime.utcnow() + timedelta(minutes=minutes_from_now)
    rome = ZoneInfo("Europe/Rome")
    local_dt = kickoff_utc.replace(tzinfo=timezone.utc).astimezone(rome)
    row = NextFixture(
        event_key=event_key,
        event_date=local_dt.date(),
        event_time=local_dt.time().replace(microsecond=0),
        event_first_player="Alice",
        event_second_player="Bob",
        tournament_name="Test Open",
        event_status="Not Started",
        odds=SAMPLE_ODDS,
        is_completed=is_completed,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_find_fixtures_pending_closing_capture_within_window(db_session):
    _seed_fixture_with_kickoff(db_session, event_key=6001, minutes_from_now=30)
    _seed_fixture_with_kickoff(db_session, event_key=6002, minutes_from_now=500)
    _seed_fixture_with_kickoff(db_session, event_key=6003, minutes_from_now=-5)

    pending = find_fixtures_pending_closing_capture(db_session, window_minutes=60)

    event_keys = [event_key for event_key, _kickoff in pending]
    assert event_keys == [6001]


def test_find_fixtures_pending_closing_capture_ignores_missing_event_time(db_session):
    row = NextFixture(
        event_key=6010,
        event_date=(datetime.utcnow() + timedelta(minutes=30)).date(),
        event_time=None,
        event_first_player="Alice",
        event_second_player="Bob",
        odds=SAMPLE_ODDS,
        is_completed=False,
    )
    db_session.add(row)
    db_session.commit()

    pending = find_fixtures_pending_closing_capture(db_session, window_minutes=60)

    assert pending == []


def test_find_fixtures_pending_closing_capture_ignores_completed(db_session):
    _seed_fixture_with_kickoff(
        db_session, event_key=6020, minutes_from_now=15, is_completed=True
    )

    pending = find_fixtures_pending_closing_capture(db_session, window_minutes=60)

    assert pending == []


def test_capture_closing_odds_for_fixture_appends_closing_rows(db_session):
    _seed_fixture_with_kickoff(db_session, event_key=6030, minutes_from_now=10)

    with patch(
        "backend.src.service.import_next_fixtures.fetch_odds_for_match",
        return_value=SAMPLE_ODDS,
    ) as fetch_mock:
        result = capture_closing_odds_for_fixture(db_session, event_key=6030)

    fetch_mock.assert_called_once_with(6030)
    assert result is not None
    assert result.inserted == 4
    assert all(item.snapshot_type == "closing" for item in result.items)

    # A second poll a few minutes later appends NEW closing rows (distinct
    # captured_at): _resolve_clv later picks the latest one per bookmaker.
    with patch(
        "backend.src.service.import_next_fixtures.fetch_odds_for_match",
        return_value=SAMPLE_ODDS,
    ):
        with patch(
            "backend.src.app.services.prematch_odds_snapshots._utc_now_naive",
            return_value=datetime.utcnow() + timedelta(minutes=5),
        ):
            second = capture_closing_odds_for_fixture(db_session, event_key=6030)
    assert second is not None
    assert second.inserted == 4

    closing_rows = list(
        db_session.scalars(
            select(PrematchOddsSnapshot).where(
                PrematchOddsSnapshot.event_key == 6030,
                PrematchOddsSnapshot.snapshot_type == "closing",
            )
        ).all()
    )
    assert len(closing_rows) == 8


def test_capture_closing_odds_for_fixture_returns_none_without_odds(db_session):
    _seed_fixture_with_kickoff(db_session, event_key=6031, minutes_from_now=10)

    with patch(
        "backend.src.service.import_next_fixtures.fetch_odds_for_match",
        return_value=None,
    ):
        result = capture_closing_odds_for_fixture(db_session, event_key=6031)

    assert result is None


def test_capture_closing_odds_for_fixture_missing_fixture_returns_none(db_session):
    with patch(
        "backend.src.service.import_next_fixtures.fetch_odds_for_match",
        return_value=SAMPLE_ODDS,
    ) as fetch_mock:
        result = capture_closing_odds_for_fixture(db_session, event_key=999999)

    fetch_mock.assert_not_called()
    assert result is None


def test_run_closing_odds_capture_once_summarizes_batch(db_session):
    _seed_fixture_with_kickoff(db_session, event_key=6040, minutes_from_now=10)
    _seed_fixture_with_kickoff(db_session, event_key=6041, minutes_from_now=20)
    _seed_fixture_with_kickoff(db_session, event_key=6042, minutes_from_now=500)

    def _fake_fetch(event_key: int):
        return None if event_key == 6041 else SAMPLE_ODDS

    with patch(
        "backend.src.service.import_next_fixtures.fetch_odds_for_match",
        side_effect=_fake_fetch,
    ):
        summary = run_closing_odds_capture_once(db_session, window_minutes=60)

    assert summary["candidates"] == 2
    assert summary["captured"] == 1
    assert summary["skipped_no_odds"] == 1
    assert summary["failed"] == 0
    assert summary["inserted_rows"] == 4
    assert set(summary["event_keys"]) == {6040, 6041}


def test_run_closing_odds_capture_once_isolates_per_fixture_failures(db_session):
    _seed_fixture_with_kickoff(db_session, event_key=6050, minutes_from_now=10)
    _seed_fixture_with_kickoff(db_session, event_key=6051, minutes_from_now=20)

    def _fake_fetch(event_key: int):
        if event_key == 6050:
            raise RuntimeError("boom")
        return SAMPLE_ODDS

    with patch(
        "backend.src.service.import_next_fixtures.fetch_odds_for_match",
        side_effect=_fake_fetch,
    ):
        summary = run_closing_odds_capture_once(db_session, window_minutes=60)

    assert summary["failed"] == 1
    assert summary["captured"] == 1



