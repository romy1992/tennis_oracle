"""Tests for the append-only pre-match odds snapshot ledger."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sqlalchemy import select

from backend.src.app.schemas.prematch_odds_snapshot import (
    PrematchOddsSnapshotCreate,
    PrematchOddsSnapshotFromPayload,
)
from backend.src.app.services.prematch_odds_snapshots import (
    PrematchOddsSnapshotError,
    compute_detection_hash,
    get_snapshot,
    list_snapshots,
    record_odds_from_stored_fixture,
    record_odds_payload,
    record_snapshot,
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
