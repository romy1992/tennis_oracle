"""Service integration tests for segment ROI analysis (live source)."""

from __future__ import annotations

from datetime import date, time, timedelta

from sqlalchemy import select

from backend.src.app.schemas.published_prediction import PublishedPredictionCreate
from backend.src.app.services.published_predictions import publish_prediction
from backend.src.app.services.segment_roi_stats import compute_segment_roi_analysis
from backend.src.entity.fixture import Fixture
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.tournaments import Tournament


def _ensure_tournament(db_session) -> None:
    existing = db_session.scalar(select(Tournament).where(Tournament.tournament_key == 8101))
    if existing is None:
        db_session.add(
            Tournament(
                tournament_key=8101,
                tournament_name="Segment ROI Open",
                tournament_sourface="Clay",
                event_type_type="ATP Singles",
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
            tournament_name="Segment ROI Open",
            tournament_key=8101,
            surface="Clay",
            event_status="Not Started",
            is_completed=False,
        )
    )
    db_session.commit()


def _publish_tip(
    db_session,
    *,
    event_key: int,
    odds: float,
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
            probability=0.62,
            odds=odds,
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
            tournament_name="Segment ROI Open",
            tournament_key=8101,
            event_type_type="ATP Singles",
            tournament_round="Quarter-finals",
        )
    )
    db_session.commit()


def test_live_segment_roi_by_surface(db_session) -> None:
    _publish_tip(db_session, event_key=89001, odds=1.8)
    _publish_tip(db_session, event_key=89002, odds=2.5)
    _complete_fixture(db_session, event_key=89001, won_first=True)
    _complete_fixture(db_session, event_key=89002, won_first=False)

    result = compute_segment_roi_analysis(
        db_session,
        source="live",
        segment_dimension="surface",
        min_segment_samples=1,
        latest_only=True,
    )

    assert result.source == "live"
    assert result.market == "match_winner"
    assert result.closed >= 2
    clay = next((item for item in result.segments if item.key == "Clay"), None)
    assert clay is not None
    assert clay.closed >= 2
    assert clay.roi_pct is not None


def test_live_segment_roi_by_favorite_role(db_session) -> None:
    _publish_tip(db_session, event_key=89003, odds=1.7)
    _publish_tip(db_session, event_key=89004, odds=3.0)
    _complete_fixture(db_session, event_key=89003, won_first=True)
    _complete_fixture(db_session, event_key=89004, won_first=True)

    result = compute_segment_roi_analysis(
        db_session,
        source="live",
        segment_dimension="favorite_role",
        min_segment_samples=1,
        latest_only=True,
    )

    populated = [item for item in result.segments if item.closed > 0]
    keys = {item.key for item in populated}
    assert "favorite" in keys
    assert "underdog" in keys
