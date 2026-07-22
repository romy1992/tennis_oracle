"""Tests for the admin live-beta dashboard aggregate."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from backend.src.app.schemas.published_prediction import PublishedPredictionCreate
from backend.src.app.services.live_beta_dashboard import compute_live_beta_dashboard
from backend.src.app.services.published_predictions import publish_prediction
from backend.src.entity.fixture import Fixture
from backend.src.entity.global_update_run import GlobalUpdateRun
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot
from backend.src.entity.telegram_bot_event import TelegramBotEvent
from backend.src.entity.tournaments import Tournament


def _ensure_tournament(db_session, *, key: int = 8101, surface: str = "Hard") -> None:
    existing = db_session.scalar(select(Tournament).where(Tournament.tournament_key == key))
    if existing is None:
        db_session.add(
            Tournament(
                tournament_key=key,
                tournament_name="Beta Open",
                tournament_sourface=surface,
            )
        )
        db_session.commit()


def _future_fixture(db_session, *, event_key: int, surface: str = "Hard") -> NextFixture:
    _ensure_tournament(db_session, surface=surface)
    row = NextFixture(
        event_key=event_key,
        event_date=date.today() + timedelta(days=2),
        event_time=time(14, 0),
        event_first_player="Alice",
        event_second_player="Bob",
        tournament_name="Beta Open",
        tournament_key=8101,
        surface=surface,
        event_status="Not Started",
        is_completed=False,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _completed_fixture(db_session, *, event_key: int, winner: str = "First Player") -> Fixture:
    _ensure_tournament(db_session, surface="Clay")
    row = Fixture(
        event_key=event_key,
        event_date=date.today() - timedelta(days=1),
        event_time=time(16, 0),
        event_first_player="Alice",
        event_second_player="Bob",
        event_winner=winner,
        event_status="Finished",
        event_final_result="2 - 0",
        tournament_name="Beta Open",
        tournament_key=8101,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _publish(
    db_session,
    *,
    event_key: int,
    odds: float = 2.0,
    published_at: datetime | None = None,
    tournament_name: str = "Beta Open",
    model_version: str = "v3",
):
    return publish_prediction(
        db_session,
        PublishedPredictionCreate(
            event_key=event_key,
            selection="Alice",
            model_version=model_version,
            model_name="logistic_regression",
            probability=0.58,
            odds=odds,
            edge=6.0,
            unit_stake=1.0,
            publication_source="admin_api",
            initial_status="published",
            tournament_name=tournament_name,
            player_1_name="Alice",
            player_2_name="Bob",
            event_date=date.today() + timedelta(days=2),
        ),
        published_at=published_at or datetime.now(),
    )


def test_live_beta_dashboard_aggregates_sections(db_session):
    _future_fixture(db_session, event_key=9301, surface="Hard")
    _publish(db_session, event_key=9301, odds=1.8)

    # Publish while still upcoming, then settle via completed fixture.
    _future_fixture(db_session, event_key=9302, surface="Clay")
    publish_prediction(
        db_session,
        PublishedPredictionCreate(
            event_key=9302,
            selection="Alice",
            model_version="v3",
            model_name="logistic_regression",
            probability=0.6,
            odds=2.2,
            edge=8.0,
            unit_stake=1.0,
            publication_source="admin_api",
            initial_status="published",
            tournament_name="Beta Open",
            player_1_name="Alice",
            player_2_name="Bob",
            event_date=date.today() - timedelta(days=1),
        ),
        published_at=datetime.now() - timedelta(days=2),
    )
    upcoming = db_session.scalar(select(NextFixture).where(NextFixture.event_key == 9302))
    if upcoming is not None:
        db_session.delete(upcoming)
        db_session.commit()
    _completed_fixture(db_session, event_key=9302)

    db_session.add(
        PrematchOddsSnapshot(
            event_key=9301,
            selection="Alice",
            bookmaker="test_book",
            odds=1.8,
            implied_probability=0.5,
            margin=0.05,
            captured_at=datetime.now(),
            source="test",
            snapshot_type="opening",
            detection_hash="hash-live-beta-9301",
        )
    )
    db_session.add(
        GlobalUpdateRun(
            run_date=date.today(),
            origin="manual",
            status="completed_with_errors",
            force="false",
            created_at=datetime.now() - timedelta(hours=1),
            started_at=datetime.now() - timedelta(hours=1),
            finished_at=datetime.now() - timedelta(minutes=30),
            errors_json='["pipeline boom"]',
            warnings_json="[]",
        )
    )
    db_session.add(
        TelegramBotEvent(
            created_at=datetime.now(),
            telegram_user_id=42,
            chat_id=42,
            username="beta_user",
            event_type="command",
            action="/schedine",
            success=False,
            error_message="timeout bot",
        )
    )
    db_session.commit()

    dashboard = compute_live_beta_dashboard(db_session)

    assert dashboard.mode == "live"
    assert dashboard.backtest.mode == "backtest"
    assert dashboard.backtest.included_in_live_kpis is False
    assert dashboard.live_stats.source == "published_prediction"
    assert dashboard.live_stats.predictions_total >= 2
    assert dashboard.live_stats.open >= 1
    assert dashboard.live_stats.closed >= 1
    assert len(dashboard.published_today) >= 1
    assert len(dashboard.open_predictions) >= 1
    assert len(dashboard.closed_predictions) >= 1
    assert dashboard.pipeline.latest_run is not None
    assert dashboard.pipeline.import_status is not None
    assert dashboard.data_completeness.tips_total >= 2
    assert dashboard.data_completeness.tips_with_odds_pct == 100.0
    assert dashboard.data_completeness.event_keys_with_odds_snapshot >= 1
    assert any(err.source == "global_update" for err in dashboard.recent_errors)
    assert any(err.source == "telegram" for err in dashboard.recent_errors)
    assert dashboard.bot_usage.total_events >= 1


def test_live_beta_dashboard_filters_surface_and_odds_band(db_session):
    _future_fixture(db_session, event_key=9401, surface="Hard")
    _publish(db_session, event_key=9401, odds=1.4)

    _future_fixture(db_session, event_key=9402, surface="Clay")
    # override surface via next fixture Clay; tournament still Hard by key — set Clay surface on row
    clay = db_session.scalar(select(NextFixture).where(NextFixture.event_key == 9402))
    assert clay is not None
    clay.surface = "Clay"
    db_session.commit()
    _publish(db_session, event_key=9402, odds=2.5)

    hard_only = compute_live_beta_dashboard(db_session, surface="Hard")
    assert hard_only.live_stats.predictions_total == 1
    assert hard_only.live_stats.open == 1

    long_odds = compute_live_beta_dashboard(db_session, odds_band="2_00_3_00")
    assert long_odds.live_stats.predictions_total == 1
    assert long_odds.open_predictions[0].odds == 2.5


def test_live_beta_dashboard_api(client, auth_headers, db_session):
    _future_fixture(db_session, event_key=9501)
    _publish(db_session, event_key=9501)

    response = client.get("/api/live-beta-dashboard", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "live"
    assert body["backtest"]["mode"] == "backtest"
    assert "live_stats" in body
    assert "pipeline" in body
    assert "data_completeness" in body
    assert "recent_errors" in body
    assert "bot_usage" in body


def test_live_beta_dashboard_requires_admin(client):
    response = client.get("/api/live-beta-dashboard")
    assert response.status_code in {401, 403}


def test_live_stats_tournament_filter(db_session):
    from backend.src.app.services.published_live_stats import compute_published_live_stats

    _future_fixture(db_session, event_key=9601)
    _publish(db_session, event_key=9601, tournament_name="Beta Open")
    _future_fixture(db_session, event_key=9602)
    _publish(db_session, event_key=9602, tournament_name="Other Cup")

    filtered = compute_published_live_stats(db_session, tournament_name="Beta")
    assert filtered.predictions_total == 1
    assert filtered.tournament_name == "Beta"
