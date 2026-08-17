"""Tests for live publication of official PLAY tips into PublishedPrediction."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import func, select

from backend.src.app.core.config import Settings
from backend.src.app.schemas.prematch_odds_snapshot import PrematchOddsSnapshotCreate
from backend.src.app.schemas.published_prediction import PublishedPredictionCreate
from backend.src.app.services.betting_slips import get_daily_betting_slips
from backend.src.app.services.live_beta_dashboard import compute_live_beta_dashboard
from backend.src.app.services.live_publication_service import (
    PUBLICATION_BOOKMAKER,
    PUBLICATION_SOURCE,
    publish_official_plays_for_day,
    resolve_public_model_config,
)
from backend.src.app.services.prematch_odds_snapshots import (
    record_snapshot,
    seal_closing_from_last_prematch,
)
from backend.src.app.services.published_live_stats import compute_published_live_stats
from backend.src.app.services.published_predictions import publish_prediction
from backend.tests.auth_helpers import make_test_settings
from backend.src.entity.betting_slip import BettingSlip, BettingSlipPick
from backend.src.entity.fixture import Fixture
from backend.src.entity.match_prediction import MatchPrediction
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot
from backend.src.entity.published_prediction import PublishedPrediction


def _sample_odds() -> dict:
    return {
        "100": {
            "Home/Away": {
                "Home": {"Book A": "1.50", "Book B": "1.55"},
                "Away": {"Book A": "2.60", "Book B": "2.50"},
            }
        }
    }


def _underdog_odds() -> dict:
    """Market odds too short for a high model favorite → NO BET / BORDERLINE."""
    return {
        "100": {
            "Home/Away": {
                "Home": {"Book A": "1.10", "Book B": "1.12"},
                "Away": {"Book A": "8.00", "Book B": "7.50"},
            }
        }
    }


def _mixed_market_odds() -> dict:
    return {
        "Home/Away": {
            "Home": {"Book A": "1.50", "Book B": "1.55"},
            "Away": {"Book A": "2.60", "Book B": "2.50"},
        },
        "Over/Under by Games in Match": {
            "Over/Under by Games in Match Over": {
                "20.5": {"Book A": "2.50", "Book B": "2.50"},
            },
            "Over/Under by Games in Match Under": {
                "20.5": {"Book A": "1.50", "Book B": "1.50"},
            },
        },
    }


def _settings(**overrides) -> Settings:
    base = {
        "live_publication_enabled": True,
        "public_model_version": "v4",
        "public_model_name": "logistic_regression",
    }
    base.update(overrides)
    return make_test_settings(**base)


def _seed_play_fixture(
    db_session,
    *,
    event_key: int = 8801,
    slip_date: date | None = None,
    model_version: str = "v4",
    model_name: str = "logistic_regression",
    prob: float = 0.75,
    odds: dict | None = None,
    event_time: time | None = None,
) -> NextFixture:
    day = slip_date or date.today() + timedelta(days=1)
    fixture = NextFixture(
        event_key=event_key,
        event_date=day,
        event_time=event_time or time(18, 0),
        event_first_player="Alice",
        event_second_player="Bob",
        tournament_name="Live Pub Open",
        surface="Hard",
        odds=odds if odds is not None else _sample_odds(),
        event_status="Not Started",
        is_completed=False,
    )
    prediction = MatchPrediction(
        event_key=event_key,
        model_version=model_version,
        model_name=model_name,
        predicted_at=datetime.utcnow(),
        prob_player_1_win=prob,
        predicted_winner="First Player",
    )
    db_session.add_all([fixture, prediction])
    db_session.commit()
    return fixture


def test_resolve_public_model_disabled_by_default():
    cfg = resolve_public_model_config(make_test_settings())
    assert cfg.status == "disabled"
    assert cfg.enabled is False
    assert cfg.warning is not None


def test_resolve_public_model_incomplete():
    cfg = resolve_public_model_config(
        make_test_settings(live_publication_enabled=True, public_model_version="v3")
    )
    assert cfg.status == "incomplete"
    assert "PUBLIC_MODEL" in (cfg.warning or "")


def test_resolve_public_model_invalid():
    cfg = resolve_public_model_config(
        make_test_settings(
            live_publication_enabled=True,
            public_model_version="v9",
            public_model_name="magic_model",
        )
    )
    assert cfg.status == "invalid"


def test_valid_play_is_published(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, slip_date=day)
    get_daily_betting_slips(
        db_session,
        slip_date=day,
        model_version="v4",
        model_name="logistic_regression",
        regenerate=True,
    )

    report = publish_official_plays_for_day(
        db_session,
        slip_date=day,
        settings=_settings(),
    )

    assert report.config_status == "ready"
    assert report.publications_created == 1
    assert report.duplicates_skipped == 0
    row = db_session.scalar(select(PublishedPrediction))
    assert row is not None
    assert row.publication_source == PUBLICATION_SOURCE
    assert row.unit_stake == 1.0
    assert row.selection == "Alice"
    assert row.match_prediction_id is not None
    assert row.model_version == "v4"
    assert row.model_name == "logistic_regression"
    snap = db_session.scalar(
        select(PrematchOddsSnapshot).where(
            PrematchOddsSnapshot.snapshot_type == "publication"
        )
    )
    assert snap is not None
    assert snap.bookmaker == PUBLICATION_BOOKMAKER
    assert snap.odds == pytest.approx(float(row.odds))


def test_official_publication_ignores_extra_market_and_links_match_winner_pick(db_session):
    day = date.today() + timedelta(days=1)
    fixture = _seed_play_fixture(db_session, slip_date=day, odds=_mixed_market_odds())
    publish_prediction(
        db_session,
        PublishedPredictionCreate(
            event_key=fixture.event_key,
            selection="Over 20.5",
            model_version="over_under_games_v1",
            model_name="random_forest",
            probability=0.90,
            odds=2.50,
            void_odds=1.1111,
            edge=125.0,
            publication_source="system",
            event_date=day,
        ),
    )
    daily = get_daily_betting_slips(
        db_session,
        slip_date=day,
        model_version="v4",
        model_name="logistic_regression",
        slip_count=1,
        picks_per_slip=2,
        regenerate=True,
    )
    assert {(pick.event_key, pick.market) for pick in daily.slips[0].picks} == {
        (fixture.event_key, "match_winner"),
        (fixture.event_key, "over_under_games"),
    }

    report = publish_official_plays_for_day(
        db_session,
        slip_date=day,
        settings=_settings(),
    )

    assert report.publications_created == 1
    official = db_session.scalar(
        select(PublishedPrediction).where(PublishedPrediction.model_version == "v4")
    )
    assert official is not None
    assert official.selection == "Alice"
    assert official.betting_slip_pick_id is not None
    linked_pick = db_session.get(BettingSlipPick, official.betting_slip_pick_id)
    assert linked_pick is not None
    assert linked_pick.market == "match_winner"


def test_non_play_is_not_published(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, slip_date=day, odds=_underdog_odds(), prob=0.55)

    report = publish_official_plays_for_day(
        db_session,
        slip_date=day,
        settings=_settings(),
    )

    assert report.publications_created == 0
    assert report.predictions_excluded >= 1
    assert report.exclusion_reasons.get("not_play", 0) >= 1
    assert db_session.scalar(select(func.count()).select_from(PublishedPrediction)) == 0


def test_non_public_model_is_not_published(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(
        db_session,
        slip_date=day,
        model_version="v2",
        model_name="random_forest",
    )

    report = publish_official_plays_for_day(
        db_session,
        slip_date=day,
        model_version="v2",
        model_name="random_forest",
        settings=_settings(),
    )

    assert report.publications_created == 0
    assert report.config_status == "invalid"
    assert db_session.scalar(select(func.count()).select_from(PublishedPrediction)) == 0


def test_publication_disabled(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, slip_date=day)

    report = publish_official_plays_for_day(
        db_session,
        slip_date=day,
        settings=make_test_settings(live_publication_enabled=False),
    )

    assert report.config_status == "disabled"
    assert report.publications_created == 0
    assert report.config_warning is not None


def test_public_config_missing(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, slip_date=day)

    report = publish_official_plays_for_day(
        db_session,
        slip_date=day,
        settings=make_test_settings(
            live_publication_enabled=True,
            public_model_version=None,
            public_model_name=None,
        ),
    )

    assert report.config_status == "incomplete"
    assert report.publications_created == 0


def test_pipeline_rerun_is_idempotent(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, slip_date=day)
    get_daily_betting_slips(
        db_session,
        slip_date=day,
        model_version="v4",
        model_name="logistic_regression",
        regenerate=True,
    )
    settings = _settings()

    first = publish_official_plays_for_day(db_session, slip_date=day, settings=settings)
    second = publish_official_plays_for_day(db_session, slip_date=day, settings=settings)

    assert first.publications_created == 1
    assert second.publications_created == 0
    assert second.duplicates_skipped == 1
    assert db_session.scalar(select(func.count()).select_from(PublishedPrediction)) == 1


def test_publish_after_kickoff_rejected(db_session):
    started_day = date.today() - timedelta(days=1)
    _seed_play_fixture(
        db_session,
        event_key=8802,
        slip_date=started_day,
        event_time=time(0, 0),
    )

    report = publish_official_plays_for_day(
        db_session,
        slip_date=started_day,
        settings=_settings(),
    )

    assert report.publications_created == 0
    assert report.exclusion_reasons.get("match_started", 0) >= 1


def test_links_match_prediction_and_play_pick(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, slip_date=day)
    get_daily_betting_slips(
        db_session,
        slip_date=day,
        model_version="v4",
        model_name="logistic_regression",
        regenerate=True,
    )

    publish_official_plays_for_day(db_session, slip_date=day, settings=_settings())
    row = db_session.scalar(select(PublishedPrediction))
    assert row is not None
    assert row.match_prediction_id is not None
    mp = db_session.get(MatchPrediction, row.match_prediction_id)
    assert mp is not None
    assert mp.event_key == row.event_key
    if row.betting_slip_pick_id is not None:
        pick = db_session.get(BettingSlipPick, row.betting_slip_pick_id)
        assert pick is not None
        slip = db_session.get(BettingSlip, pick.betting_slip_id)
        assert slip is not None
        assert slip.slip_key.startswith("play_")


def test_publication_snapshot_duplicate_skipped(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, slip_date=day)
    get_daily_betting_slips(
        db_session,
        slip_date=day,
        model_version="v4",
        model_name="logistic_regression",
        regenerate=True,
    )
    settings = _settings()
    publish_official_plays_for_day(db_session, slip_date=day, settings=settings)

    row = db_session.scalar(select(PublishedPrediction))
    assert row is not None
    # Same second / same fingerprint → skipped
    again = record_snapshot(
        db_session,
        PrematchOddsSnapshotCreate(
            event_key=row.event_key,
            selection=row.selection,
            bookmaker=PUBLICATION_BOOKMAKER,
            odds=float(row.odds),
            source="publication",
            snapshot_type="publication",
            captured_at=row.published_at,
        ),
    )
    assert again is None
    count = db_session.scalar(
        select(func.count())
        .select_from(PrematchOddsSnapshot)
        .where(PrematchOddsSnapshot.snapshot_type == "publication")
    )
    assert count == 1


def test_closing_absent_not_invented(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, event_key=8810, slip_date=day)
    result = seal_closing_from_last_prematch(db_session, event_key=8810)
    assert result.inserted == 0
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PrematchOddsSnapshot)
            .where(PrematchOddsSnapshot.snapshot_type == "closing")
        )
        == 0
    )


def test_closing_sealed_from_prematch_only(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, event_key=8811, slip_date=day)
    pre_kickoff = datetime.utcnow() - timedelta(hours=2)
    record_snapshot(
        db_session,
        PrematchOddsSnapshotCreate(
            event_key=8811,
            selection="Alice",
            bookmaker="Book A",
            odds=1.55,
            source="import",
            snapshot_type="opening",
            captured_at=pre_kickoff,
        ),
    )
    result = seal_closing_from_last_prematch(db_session, event_key=8811)
    assert result.inserted == 1
    closing = db_session.scalar(
        select(PrematchOddsSnapshot).where(
            PrematchOddsSnapshot.snapshot_type == "closing"
        )
    )
    assert closing is not None
    assert closing.odds == pytest.approx(1.55)
    assert closing.captured_at.replace(microsecond=0) == pre_kickoff.replace(microsecond=0)

    # Idempotent
    again = seal_closing_from_last_prematch(db_session, event_key=8811)
    assert again.inserted == 0


def test_kpi_update_and_settlement_after_publication(db_session):
    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, event_key=8820, slip_date=day)
    get_daily_betting_slips(
        db_session,
        slip_date=day,
        model_version="v4",
        model_name="logistic_regression",
        regenerate=True,
    )
    publish_official_plays_for_day(db_session, slip_date=day, settings=_settings())

    stats_open = compute_published_live_stats(db_session)
    assert stats_open.predictions_total == 1
    assert stats_open.open == 1

    # Settle: remove upcoming, add finished fixture
    upcoming = db_session.scalar(select(NextFixture).where(NextFixture.event_key == 8820))
    db_session.delete(upcoming)
    db_session.add(
        Fixture(
            event_key=8820,
            event_date=day,
            event_time=time(18, 0),
            event_first_player="Alice",
            event_second_player="Bob",
            event_winner="First Player",
            event_status="Finished",
            tournament_name="Live Pub Open",
        )
    )
    db_session.commit()

    stats_closed = compute_published_live_stats(db_session)
    assert stats_closed.won == 1
    assert stats_closed.lost == 0
    assert stats_closed.void == 0
    assert stats_closed.profit > 0


def test_dashboard_empty_state_disabled(db_session):
    from backend.tests.auth_helpers import override_settings, clear_settings_override

    override_settings(make_test_settings(live_publication_enabled=False))
    try:
        dashboard = compute_live_beta_dashboard(db_session)
        assert dashboard.publication_health.empty_reason == "publication_disabled"
        assert "LIVE_PUBLICATION_ENABLED" in dashboard.publication_health.message
        assert dashboard.live_stats.predictions_total == 0
    finally:
        clear_settings_override()


def test_dashboard_populated_after_publication(db_session):
    from backend.tests.auth_helpers import override_settings, clear_settings_override

    day = date.today() + timedelta(days=1)
    _seed_play_fixture(db_session, slip_date=day)
    get_daily_betting_slips(
        db_session,
        slip_date=day,
        model_version="v4",
        model_name="logistic_regression",
        regenerate=True,
    )
    settings = _settings()
    override_settings(settings)
    try:
        publish_official_plays_for_day(db_session, slip_date=day, settings=settings)
        dashboard = compute_live_beta_dashboard(db_session)
        assert dashboard.live_stats.predictions_total == 1
        assert dashboard.publication_health.empty_reason == "ok"
        assert dashboard.publication_health.public_model_version == "v4"
        assert dashboard.publication_health.validation_started_at is not None
        assert dashboard.data_completeness.snapshots_publication >= 1
        assert dashboard.data_completeness.closing_odds_note is not None
    finally:
        clear_settings_override()
