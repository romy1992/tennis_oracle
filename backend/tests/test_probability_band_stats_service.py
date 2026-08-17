"""Service integration tests for probability band analysis (live source)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from backend.src.app.schemas.published_prediction import PublishedPredictionCreate
from backend.src.app.services.probability_band_stats import compute_probability_band_analysis
from backend.src.app.services.published_predictions import publish_prediction
from backend.src.entity.fixture import Fixture
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.tournaments import Tournament


def _ensure_tournament(db_session) -> None:
    existing = db_session.scalar(select(Tournament).where(Tournament.tournament_key == 8001))
    if existing is None:
        db_session.add(
            Tournament(
                tournament_key=8001,
                tournament_name="Band Stats Open",
                tournament_sourface="Hard",
            )
        )
        db_session.commit()


def _future_fixture(db_session, *, event_key: int) -> None:
    _ensure_tournament(db_session)
    db_session.add(
        NextFixture(
            event_key=event_key,
            event_date=date.today() + timedelta(days=5),
            event_time=time(14, 0),
            event_first_player="Alpha",
            event_second_player="Beta",
            tournament_name="Band Stats Open",
            tournament_key=8001,
            surface="Hard",
            event_status="Not Started",
            is_completed=False,
        )
    )
    db_session.commit()


def _publish_tip(
    db_session,
    *,
    event_key: int,
    probability: float,
    selection: str = "Alpha",
) -> None:
    _future_fixture(db_session, event_key=event_key)
    publish_prediction(
        db_session,
        PublishedPredictionCreate(
            event_key=event_key,
            selection=selection,
            model_version="v4",
            model_name="voting_ensemble",
            probability=probability,
            odds=2.0,
            edge=6.0,
            unit_stake=1.0,
            publication_source="admin_api",
            initial_status="published",
            player_1_name="Alpha",
            player_2_name="Beta",
            event_date=date.today() + timedelta(days=5),
        ),
    )


def _complete_fixture(db_session, *, event_key: int, won_first: bool) -> None:
    event_day = date.today() - timedelta(days=2)
    db_session.add(
        Fixture(
            event_key=event_key,
            event_date=event_day,
            event_time=time(16, 0),
            event_first_player="Alpha",
            event_second_player="Beta",
            event_winner="First Player" if won_first else "Second Player",
            event_status="Finished",
            event_final_result="2 - 0",
            tournament_name="Band Stats Open",
            tournament_key=8001,
        )
    )
    db_session.commit()


def test_live_probability_band_analysis(db_session) -> None:
    _publish_tip(db_session, event_key=88001, probability=0.62)
    _publish_tip(db_session, event_key=88002, probability=0.58)
    _complete_fixture(db_session, event_key=88001, won_first=True)
    _complete_fixture(db_session, event_key=88002, won_first=False)

    result = compute_probability_band_analysis(
        db_session,
        source="live",
        band_dimension="probability",
        n_bins=5,
        min_bin_samples=1,
        latest_only=True,
    )

    assert result.source == "live"
    assert result.market == "match_winner"
    assert result.closed >= 2
    assert len(result.bands) == 5
    populated = [band for band in result.bands if band.closed > 0]
    assert populated
    assert populated[0].hit_rate_pct is not None
