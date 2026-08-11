"""Tests for the CLV ML-readiness diagnostic (check_clv_ml_readiness.py)."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from backend.src.app.ml.training.check_clv_ml_readiness import (
    RESULTS_FILENAME,
    run_clv_ml_readiness_check,
)
from backend.src.app.schemas.published_prediction import PublishedPredictionCreate
from backend.src.app.services.published_predictions import publish_prediction
from backend.src.entity.fixture import Fixture
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot

# Stessi helper minimi di test_published_live_stats.py (duplicati per tenere il
# test isolato/indipendente, stessa convenzione di test_train_v4_voting.py).


def _future_fixture(db_session, *, event_key: int) -> NextFixture:
    # Sempre nel futuro reale (gate anti-pubblicazione-a-partita-iniziata in
    # publish_prediction usa NextFixture.event_date/event_time, indipendente
    # dalla data "storica" usata per il raggruppamento settimanale sotto).
    row = NextFixture(
        event_key=event_key,
        event_date=date.today() + timedelta(days=3),
        event_time=time(14, 0),
        event_first_player="Alice",
        event_second_player="Bob",
        tournament_name="Readiness Open",
        tournament_key=8001,
        surface="Hard",
        event_status="Not Started",
        is_completed=False,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _publish(db_session, *, event_key: int, event_day: date, published_at: datetime):
    _future_fixture(db_session, event_key=event_key)
    payload = PublishedPredictionCreate(
        event_key=event_key,
        selection="Alice",
        model_version="v3",
        model_name="logistic_regression",
        probability=0.60,
        odds=2.0,
        void_odds=1.6667,
        edge=5.0,
        unit_stake=1.0,
        publication_source="admin_api",
        initial_status="published",
        event_date=event_day,
        player_1_name="Alice",
        player_2_name="Bob",
    )
    return publish_prediction(db_session, payload, published_at=published_at)


def _add_snapshot_pair(
    db_session, *, event_key: int, snapshot_type: str, bookmaker: str, captured_at: datetime
) -> None:
    db_session.add(
        PrematchOddsSnapshot(
            event_key=event_key,
            selection="Alice",
            bookmaker=bookmaker,
            odds=2.0,
            implied_probability=0.5,
            margin=0.04,
            captured_at=captured_at,
            source="test",
            snapshot_type=snapshot_type,
            detection_hash=f"{event_key}-{snapshot_type}-{bookmaker}-alice-{captured_at.isoformat()}",
        )
    )
    db_session.add(
        PrematchOddsSnapshot(
            event_key=event_key,
            selection="Bob",
            bookmaker=bookmaker,
            odds=1.9,
            implied_probability=0.526,
            margin=0.04,
            captured_at=captured_at,
            source="test",
            snapshot_type=snapshot_type,
            detection_hash=f"{event_key}-{snapshot_type}-{bookmaker}-bob-{captured_at.isoformat()}",
        )
    )
    db_session.commit()


def _monday(base: date) -> date:
    return base - timedelta(days=base.weekday())


def _completed_fixture(db_session, *, event_key: int, event_day: date, winner: str = "First Player") -> Fixture:
    # Fixture (completata) ha priorita' su NextFixture in _load_match_contexts:
    # non serve cancellare la NextFixture creata da _publish/_future_fixture.
    # winner: "First Player" (Alice vince) o "Second Player" (Bob vince) — vedi
    # match_lifecycle.COMPLETED_WINNERS (non il nome del giocatore).
    row = Fixture(
        event_key=event_key,
        event_date=event_day,
        event_time=time(16, 0),
        event_first_player="Alice",
        event_second_player="Bob",
        event_winner=winner,
        event_status="Finished",
        event_final_result="2 - 0",
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_ready_is_false_below_threshold_and_report_is_persisted(db_session, tmp_path):
    week1 = _monday(date(2026, 1, 5))
    _publish(db_session, event_key=9201, event_day=week1, published_at=datetime.combine(week1, time(10, 0)))
    _add_snapshot_pair(db_session, event_key=9201, snapshot_type="publication", bookmaker="book_a",
                        captured_at=datetime.combine(week1, time(10, 0)))
    _add_snapshot_pair(db_session, event_key=9201, snapshot_type="closing", bookmaker="book_a",
                        captured_at=datetime.combine(week1, time(13, 0)))
    _completed_fixture(db_session, event_key=9201, event_day=week1, winner="First Player")

    # Seconda tip nella stessa settimana, senza closing: contribuisce a total ma non a with_clv.
    _publish(db_session, event_key=9202, event_day=week1, published_at=datetime.combine(week1, time(11, 0)))
    _add_snapshot_pair(db_session, event_key=9202, snapshot_type="publication", bookmaker="book_b",
                        captured_at=datetime.combine(week1, time(11, 0)))
    _completed_fixture(db_session, event_key=9202, event_day=week1, winner="Second Player")

    report = run_clv_ml_readiness_check(db=db_session, min_useful_samples=200, reports_dir=tmp_path)

    assert report["closed_bets_with_clv_available"] == 1
    assert report["ready_for_target_design"] is False
    assert report["summary"]["predictions_total"] == 2
    assert report["weeks_total"] == 1
    week_entry = report["weekly_breakdown"][0]
    assert week_entry["total"] == 2
    assert week_entry["with_clv"] == 1

    results_path = tmp_path / RESULTS_FILENAME
    assert results_path.exists()
    with results_path.open("r", encoding="utf-8") as handle:
        persisted = json.load(handle)
    assert persisted["ready_for_target_design"] is False


def test_ready_becomes_true_when_threshold_is_low(db_session, tmp_path):
    week1 = _monday(date(2026, 2, 2))
    _publish(db_session, event_key=9301, event_day=week1, published_at=datetime.combine(week1, time(9, 0)))
    _add_snapshot_pair(db_session, event_key=9301, snapshot_type="publication", bookmaker="book_a",
                        captured_at=datetime.combine(week1, time(9, 0)))
    _add_snapshot_pair(db_session, event_key=9301, snapshot_type="closing", bookmaker="book_a",
                        captured_at=datetime.combine(week1, time(12, 0)))
    _completed_fixture(db_session, event_key=9301, event_day=week1, winner="First Player")

    report = run_clv_ml_readiness_check(db=db_session, min_useful_samples=1, reports_dir=tmp_path)

    assert report["closed_bets_with_clv_available"] >= 1
    assert report["ready_for_target_design"] is True


def test_weekly_breakdown_flags_zero_coverage_week(db_session, tmp_path):
    week1 = _monday(date(2026, 3, 2))
    week2 = week1 + timedelta(days=7)

    # Settimana 1: CLV disponibile.
    _publish(db_session, event_key=9401, event_day=week1, published_at=datetime.combine(week1, time(9, 0)))
    _add_snapshot_pair(db_session, event_key=9401, snapshot_type="publication", bookmaker="book_a",
                        captured_at=datetime.combine(week1, time(9, 0)))
    _add_snapshot_pair(db_session, event_key=9401, snapshot_type="closing", bookmaker="book_a",
                        captured_at=datetime.combine(week1, time(12, 0)))

    # Settimana 2: nessun closing -> copertura zero.
    _publish(db_session, event_key=9402, event_day=week2, published_at=datetime.combine(week2, time(9, 0)))
    _add_snapshot_pair(db_session, event_key=9402, snapshot_type="publication", bookmaker="book_b",
                        captured_at=datetime.combine(week2, time(9, 0)))

    report = run_clv_ml_readiness_check(db=db_session, reports_dir=tmp_path)

    assert report["weeks_total"] == 2
    assert report["weeks_with_zero_clv_coverage"] == 1
    zero_week = next(item for item in report["weekly_breakdown"] if item["with_clv"] == 0)
    assert zero_week["total"] == 1


if __name__ == "__main__":
    import pytest

    pytest.main([__file__])










