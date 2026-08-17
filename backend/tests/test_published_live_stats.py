"""Integration tests for published live tipbook statistics."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from backend.src.app.ml.prediction.extra_markets_predictor import (
    FIRST_SET_WINNER_MODEL_VERSION,
    OVER_UNDER_GAMES_MODEL_VERSION,
)
from backend.src.app.schemas.published_prediction import (
    PublishedPredictionCorrection,
    PublishedPredictionCreate,
)
from backend.src.app.services.live_betting_metrics import hit_rate_pct, roi_pct
from backend.src.app.services.published_live_stats import (
    compute_published_live_stats,
    edge_bucket,
    list_settled_published_tips,
    odds_bucket,
    selection_to_predicted_winner,
)
from backend.src.app.services.published_predictions import (
    correct_published_prediction,
    publish_prediction,
)
from backend.src.entity.fixture import Fixture
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot
from backend.src.entity.tournaments import Tournament


def _future_fixture(db_session, *, event_key: int, surface: str = "Hard") -> NextFixture:
    row = NextFixture(
        event_key=event_key,
        event_date=date.today() + timedelta(days=3),
        event_time=time(14, 0),
        event_first_player="Alice",
        event_second_player="Bob",
        tournament_name="Live Stats Open",
        tournament_key=7001,
        surface=surface,
        event_status="Not Started",
        is_completed=False,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _ensure_clay_tournament(db_session, *, surface: str = "Clay") -> None:
    existing = db_session.scalar(select(Tournament).where(Tournament.tournament_key == 7002))
    if existing is None:
        db_session.add(
            Tournament(
                tournament_key=7002,
                tournament_name="Clay Masters",
                tournament_sourface=surface,
            )
        )
        db_session.commit()


def _completed_fixture(
    db_session,
    *,
    event_key: int,
    winner: str,
    event_day: date,
    surface: str = "Clay",
    status: str = "Finished",
    scores: list[dict] | None = None,
) -> Fixture:
    _ensure_clay_tournament(db_session, surface=surface)
    row = Fixture(
        event_key=event_key,
        event_date=event_day,
        event_time=time(16, 0),
        event_first_player="Alice",
        event_second_player="Bob",
        event_winner=winner,
        event_status=status,
        event_final_result="2 - 0",
        tournament_name="Clay Masters",
        tournament_key=7002,
        scores=scores,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _cancelled_fixture(db_session, *, event_key: int, event_day: date) -> Fixture:
    _ensure_clay_tournament(db_session)
    row = Fixture(
        event_key=event_key,
        event_date=event_day,
        event_time=time(12, 0),
        event_first_player="Alice",
        event_second_player="Bob",
        event_winner=None,
        event_status="Cancelled",
        tournament_name="Clay Masters",
        tournament_key=7002,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _publish(
    db_session,
    *,
    event_key: int,
    selection: str,
    odds: float | None,
    stake: float,
    edge: float | None,
    model_version: str = "v3",
    model_name: str = "logistic_regression",
    published_at: datetime | None = None,
    event_day: date | None = None,
    market: str | None = None,
    value_decision: str | None = None,
    official_play: bool = False,
    publication_source: str = "admin_api",
    initial_status: str = "published",
):
    _future_fixture(db_session, event_key=event_key)
    resolved_market = market
    if resolved_market is None:
        if model_version == FIRST_SET_WINNER_MODEL_VERSION:
            resolved_market = "first_set_winner"
        elif model_version == OVER_UNDER_GAMES_MODEL_VERSION:
            resolved_market = "over_under_games"
        else:
            resolved_market = "match_winner"
    payload = PublishedPredictionCreate(
        event_key=event_key,
        market=resolved_market,
        value_decision=value_decision,
        official_play=official_play,
        selection=selection,
        model_version=model_version,
        model_name=model_name,
        probability=0.60,
        odds=odds,
        void_odds=1.6667,
        edge=edge,
        unit_stake=stake,
        publication_source=publication_source,
        initial_status=initial_status,
        event_date=event_day or (date.today() + timedelta(days=3)),
        player_1_name="Alice",
        player_2_name="Bob",
    )
    return publish_prediction(db_session, payload, published_at=published_at)


def _add_snapshot_pair(
    db_session,
    *,
    event_key: int,
    snapshot_type: str,
    bookmaker: str,
    captured_at: datetime,
    alice_odds: float,
    bob_odds: float,
    market: str = "match_winner",
    market_line: float | None = None,
) -> None:
    db_session.add(
        PrematchOddsSnapshot(
            event_key=event_key,
            market=market,
            market_line=market_line,
            selection="Alice",
            bookmaker=bookmaker,
            odds=alice_odds,
            implied_probability=1 / alice_odds,
            margin=(1 / alice_odds) + (1 / bob_odds) - 1,
            captured_at=captured_at,
            source="test",
            snapshot_type=snapshot_type,
            detection_hash=(
                f"{event_key}-{market}-{market_line}-{snapshot_type}-"
                f"{bookmaker}-alice-{captured_at.isoformat()}"
            ),
        )
    )
    db_session.add(
        PrematchOddsSnapshot(
            event_key=event_key,
            market=market,
            market_line=market_line,
            selection="Bob",
            bookmaker=bookmaker,
            odds=bob_odds,
            implied_probability=1 / bob_odds,
            margin=(1 / alice_odds) + (1 / bob_odds) - 1,
            captured_at=captured_at,
            source="test",
            snapshot_type=snapshot_type,
            detection_hash=(
                f"{event_key}-{market}-{market_line}-{snapshot_type}-"
                f"{bookmaker}-bob-{captured_at.isoformat()}"
            ),
        )
    )
    db_session.commit()


def test_selection_mapping():
    assert selection_to_predicted_winner("Alice", "Alice", "Bob") == "First Player"
    assert selection_to_predicted_winner("Bob", "Alice", "Bob") == "Second Player"
    assert selection_to_predicted_winner("First Player", "Alice", "Bob") == "First Player"
    assert selection_to_predicted_winner("Charlie", "Alice", "Bob") is None


def test_odds_and_edge_buckets():
    assert odds_bucket(1.4) == "lt_1_50"
    assert odds_bucket(1.8) == "1_50_2_00"
    assert odds_bucket(2.5) == "2_00_3_00"
    assert odds_bucket(3.2) == "gte_3_00"
    assert odds_bucket(None) == "missing"
    assert edge_bucket(-1.0) == "lt_0"
    assert edge_bucket(3.0) == "0_5"
    assert edge_bucket(7.0) == "5_10"
    assert edge_bucket(12.0) == "gte_10"
    assert edge_bucket(None) == "missing"


def test_live_stats_known_numeric_case(db_session):
    """Hand-computed P/L on four published tips.

    1. Alice @ 2.0 stake 1 → won → profit +1.0
    2. Alice @ 1.5 stake 2 → lost → profit -2.0
    3. Bob @ 3.0 stake 1 → void (cancelled) → profit 0, stake excluded
    4. Alice @ 2.0 stake 1 → still open (future) → profit 0

    Closed: won=1 lost=1 → hit rate 50%
    Stake total = 1+2+1+1 = 5
    Stake settled = 1+2 = 3
    Profit = -1
    ROI = yield = -1/3 * 100 ≈ -33.3333%
    Max drawdown on closed chrono (+1, -2): equity 0→1→-1; peak 1; DD = 2
    Streaks: W then L → max win 1, max loss 1
    """
    day1 = date(2026, 6, 1)
    day2 = date(2026, 6, 2)
    day3 = date(2026, 6, 3)

    tip1 = _publish(
        db_session,
        event_key=9101,
        selection="Alice",
        odds=2.0,
        stake=1.0,
        edge=8.0,
        event_day=day1,
        published_at=datetime(2026, 5, 30, 10, 0, 0),
    )
    tip2 = _publish(
        db_session,
        event_key=9102,
        selection="Alice",
        odds=1.5,
        stake=2.0,
        edge=2.0,
        event_day=day2,
        published_at=datetime(2026, 5, 30, 11, 0, 0),
    )
    tip3 = _publish(
        db_session,
        event_key=9103,
        selection="Bob",
        odds=3.0,
        stake=1.0,
        edge=12.0,
        event_day=day3,
        published_at=datetime(2026, 5, 30, 12, 0, 0),
    )
    tip4 = _publish(
        db_session,
        event_key=9104,
        selection="Alice",
        odds=2.0,
        stake=1.0,
        edge=4.0,
        model_version="v2",
        model_name="random_forest",
        published_at=datetime(2026, 5, 30, 13, 0, 0),
    )

    for key in (9101, 9102, 9103):
        row = db_session.scalar(select(NextFixture).where(NextFixture.event_key == key))
        if row is not None:
            db_session.delete(row)
    db_session.commit()

    _completed_fixture(
        db_session, event_key=9101, winner="First Player", event_day=day1, surface="Clay"
    )
    _completed_fixture(
        db_session, event_key=9102, winner="Second Player", event_day=day2, surface="Clay"
    )
    _cancelled_fixture(db_session, event_key=9103, event_day=day3)

    _add_snapshot_pair(
        db_session,
        event_key=9101,
        snapshot_type="publication",
        bookmaker="book_a",
        captured_at=datetime(2026, 5, 30, 10, 0, 0),
        alice_odds=2.0,
        bob_odds=1.8,
    )
    _add_snapshot_pair(
        db_session,
        event_key=9101,
        snapshot_type="closing",
        bookmaker="book_a",
        captured_at=datetime(2026, 5, 30, 14, 0, 0),
        alice_odds=1.8,
        bob_odds=2.0,
    )
    _add_snapshot_pair(
        db_session,
        event_key=9102,
        snapshot_type="publication",
        bookmaker="book_b",
        captured_at=datetime(2026, 5, 30, 11, 0, 0),
        alice_odds=1.5,
        bob_odds=2.5,
    )
    _add_snapshot_pair(
        db_session,
        event_key=9102,
        snapshot_type="closing",
        bookmaker="book_c",
        captured_at=datetime(2026, 5, 30, 15, 0, 0),
        alice_odds=1.6,
        bob_odds=2.3,
    )

    stats = compute_published_live_stats(db_session)

    assert tip1.id and tip2.id and tip3.id and tip4.id
    assert stats.predictions_total == 4
    assert stats.won == 1
    assert stats.lost == 1
    assert stats.void == 1
    assert stats.open == 1
    assert stats.closed == 2
    assert stats.hit_rate_pct == hit_rate_pct(1, 1)
    assert stats.stake_total == 5.0
    assert stats.stake_settled == 3.0
    assert stats.profit == -1.0
    assert round(stats.roi_pct or 0.0, 4) == round(roi_pct(-1.0, 3.0) or 0.0, 4)
    assert stats.yield_pct == stats.roi_pct
    assert stats.avg_odds == 2.125
    assert stats.max_drawdown == 2.0
    assert stats.max_winning_streak == 1
    assert stats.max_losing_streak == 1
    assert stats.clv_count == 2
    assert stats.clv_missing == 2
    assert round(stats.clv_coverage_pct or 0.0, 4) == 50.0
    assert round(stats.clv_avg_pct or 0.0, 4) == 2.4306
    assert round(stats.clv_median_pct or 0.0, 4) == 2.4306
    assert round(stats.clv_positive_pct or 0.0, 4) == 50.0

    settled_items = list_settled_published_tips(db_session, latest_only=True)
    event_9101 = next(item for item in settled_items if item.event_key == 9101)
    event_9102 = next(item for item in settled_items if item.event_key == 9102)
    event_9104 = next(item for item in settled_items if item.event_key == 9104)
    assert round(event_9101.clv_pct or 0.0, 4) == 11.1111
    assert round(event_9102.clv_pct or 0.0, 4) == -6.25
    assert event_9104.clv_pct is None

    model_keys = {bucket.key for bucket in stats.by_model}
    assert "v3|logistic_regression" in model_keys
    assert "v2|random_forest" in model_keys

    clay = next(bucket for bucket in stats.by_surface if bucket.key == "Clay")
    assert clay.predictions_total == 3

    assert any(bucket.key == "2026-06" for bucket in stats.by_period)
    assert stats.source == "published_prediction"


def test_live_stats_latest_only_excludes_superseded_versions(db_session):
    _future_fixture(db_session, event_key=9201)
    first = publish_prediction(
        db_session,
        PublishedPredictionCreate(
            event_key=9201,
            selection="Alice",
            model_version="v3",
            model_name="logistic_regression",
            probability=0.55,
            odds=2.0,
            unit_stake=1.0,
            publication_source="admin_api",
            initial_status="published",
            edge=5.0,
        ),
    )
    correct_published_prediction(
        db_session,
        previous_id=first.id,
        payload=PublishedPredictionCorrection(
            odds=1.8,
            unit_stake=2.0,
            publication_source="admin_api",
            initial_status="published",
        ),
    )

    all_versions = compute_published_live_stats(db_session, latest_only=False)
    latest = compute_published_live_stats(db_session, latest_only=True)
    assert all_versions.predictions_total == 2
    assert latest.predictions_total == 1
    assert latest.stake_total == 2.0


def test_first_set_winner_settled_against_set_score_not_match_winner(db_session):
    """A first-set-winner tip must be judged on who won SET 1, never on who
    won the overall match: Alice takes set 1 but Bob wins the match 2-1.
    Before the fix this was (wrongly) settled against the match winner.
    """
    tip = _publish(
        db_session,
        event_key=9301,
        selection="First Player",
        odds=1.9,
        stake=1.0,
        edge=5.0,
        model_version=FIRST_SET_WINNER_MODEL_VERSION,
        model_name="random_forest",
        event_day=date(2026, 6, 10),
    )
    db_session.delete(
        db_session.scalar(select(NextFixture).where(NextFixture.event_key == 9301))
    )
    db_session.commit()
    _completed_fixture(
        db_session,
        event_key=9301,
        winner="Second Player",  # Bob wins the MATCH
        event_day=date(2026, 6, 10),
        scores=[
            {"score_first": "6", "score_second": "4", "score_set": "1"},  # Alice wins set 1
            {"score_first": "3", "score_second": "6", "score_set": "2"},
            {"score_first": "2", "score_second": "6", "score_set": "3"},
        ],
    )

    settled = list_settled_published_tips(
        db_session, model_version=FIRST_SET_WINNER_MODEL_VERSION
    )
    item = next(row for row in settled if row.event_key == 9301)
    assert item.outcome == "won"
    assert round(item.profit, 4) == 0.9  # stake 1.0 @ 1.9 -> +0.9
    assert tip.id


def test_retirement_after_valid_first_set_settles_first_set_but_voids_total_games(
    db_session,
):
    event_key = 9309
    event_day = date(2026, 6, 10)
    _future_fixture(db_session, event_key=event_key)
    first_set_tip = publish_prediction(
        db_session,
        PublishedPredictionCreate(
            event_key=event_key,
            market="first_set_winner",
            selection="First Player",
            model_version=FIRST_SET_WINNER_MODEL_VERSION,
            model_name="random_forest",
            probability=0.60,
            odds=1.90,
            void_odds=1.6667,
            edge=14.0,
            publication_source="system",
            event_date=event_day,
            player_1_name="Alice",
            player_2_name="Bob",
        ),
    )
    total_games_tip = publish_prediction(
        db_session,
        PublishedPredictionCreate(
            event_key=event_key,
            market="over_under_games",
            selection="Over 20.5",
            model_version=OVER_UNDER_GAMES_MODEL_VERSION,
            model_name="random_forest",
            probability=0.60,
            odds=1.90,
            void_odds=1.6667,
            edge=14.0,
            publication_source="system",
            event_date=event_day,
            player_1_name="Alice",
            player_2_name="Bob",
        ),
    )
    db_session.delete(
        db_session.scalar(select(NextFixture).where(NextFixture.event_key == event_key))
    )
    db_session.commit()
    _completed_fixture(
        db_session,
        event_key=event_key,
        winner="Second Player",
        event_day=event_day,
        status="Retired",
        scores=[
            {"score_first": "6", "score_second": "4", "score_set": "1"},
            {"score_first": "2", "score_second": "1", "score_set": "2"},
        ],
    )

    settled = list_settled_published_tips(db_session)
    by_id = {item.id: item for item in settled}
    assert by_id[first_set_tip.id].outcome == "won"
    assert by_id[total_games_tip.id].outcome == "void"


def test_first_set_without_odds_keeps_outcome_but_excludes_financials(db_session):
    """Generator-style first-set tips have no real quote: their sporting
    outcome counts for hit rate, but stake/profit/ROI must stay unavailable."""
    tip = _publish(
        db_session,
        event_key=9308,
        selection="Second Player",
        odds=None,
        stake=1.0,
        edge=None,
        model_version=FIRST_SET_WINNER_MODEL_VERSION,
        model_name="random_forest",
        event_day=date(2026, 6, 10),
    )
    db_session.delete(
        db_session.scalar(select(NextFixture).where(NextFixture.event_key == 9308))
    )
    db_session.commit()
    _completed_fixture(
        db_session,
        event_key=9308,
        winner="Second Player",
        event_day=date(2026, 6, 10),
        scores=[
            {"score_first": "6", "score_second": "4", "score_set": "1"},
            {"score_first": "3", "score_second": "6", "score_set": "2"},
            {"score_first": "2", "score_second": "6", "score_set": "3"},
        ],
    )

    settled = list_settled_published_tips(
        db_session, model_version=FIRST_SET_WINNER_MODEL_VERSION
    )
    item = next(row for row in settled if row.id == tip.id)
    assert item.outcome == "lost"
    assert item.stake_settled == 0.0
    assert item.profit == 0.0

    stats = compute_published_live_stats(
        db_session, model_version=FIRST_SET_WINNER_MODEL_VERSION
    )
    assert stats.closed == 1
    assert stats.lost == 1
    assert stats.hit_rate_pct == 0.0
    assert stats.stake_total == 0.0
    assert stats.stake_settled == 0.0
    assert stats.profit == 0.0
    assert stats.roi_pct is None
    assert stats.yield_pct is None
    assert stats.avg_odds is None


def test_first_set_winner_pending_while_match_not_yet_finished(db_session):
    """Match still upcoming (no ``Fixture`` row yet): stays pending."""
    _publish(
        db_session,
        event_key=9302,
        selection="First Player",
        odds=1.9,
        stake=1.0,
        edge=5.0,
        model_version=FIRST_SET_WINNER_MODEL_VERSION,
        model_name="random_forest",
        event_day=date(2026, 6, 11),
    )

    settled = list_settled_published_tips(
        db_session, model_version=FIRST_SET_WINNER_MODEL_VERSION
    )
    item = next(row for row in settled if row.event_key == 9302)
    assert item.outcome == "pending"


def test_first_set_winner_void_when_finished_but_score_not_yet_available(db_session):
    """Match reported as finished but detailed score not imported yet: settles
    as void for THIS market (never a guessed won/lost). Settlement is computed
    at read time, so once ``scores`` arrives this self-corrects to won/lost."""
    _publish(
        db_session,
        event_key=9306,
        selection="First Player",
        odds=1.9,
        stake=1.0,
        edge=5.0,
        model_version=FIRST_SET_WINNER_MODEL_VERSION,
        model_name="random_forest",
        event_day=date(2026, 6, 11),
    )
    db_session.delete(
        db_session.scalar(select(NextFixture).where(NextFixture.event_key == 9306))
    )
    db_session.commit()
    _completed_fixture(
        db_session,
        event_key=9306,
        winner="First Player",
        event_day=date(2026, 6, 11),
        scores=None,
    )

    settled = list_settled_published_tips(
        db_session, model_version=FIRST_SET_WINNER_MODEL_VERSION
    )
    item = next(row for row in settled if row.event_key == 9306)
    assert item.outcome == "void"


def test_over_under_games_settled_against_total_games(db_session):
    """Over/Under-games tips are settled against the parsed total games count,
    not against any player name (the selection has no player reference)."""
    tip_over = _publish(
        db_session,
        event_key=9303,
        selection="Over 20.5",
        odds=1.9,
        stake=1.0,
        edge=5.0,
        model_version=OVER_UNDER_GAMES_MODEL_VERSION,
        model_name="random_forest",
        event_day=date(2026, 6, 12),
    )
    # Second publication on the SAME event: NextFixture.event_key is unique,
    # so bypass the `_publish` helper (which would try to insert it again).
    tip_under = publish_prediction(
        db_session,
        PublishedPredictionCreate(
            event_key=9303,
            market="over_under_games",
            selection="Under 20.5",
            model_version=OVER_UNDER_GAMES_MODEL_VERSION,
            model_name="random_forest",
            probability=0.55,
            odds=1.9,
            edge=5.0,
            unit_stake=1.0,
            publication_source="admin_api",
            initial_status="published",
            event_date=date(2026, 6, 12),
            player_1_name="Alice",
            player_2_name="Bob",
        ),
    )
    db_session.delete(
        db_session.scalar(select(NextFixture).where(NextFixture.event_key == 9303))
    )
    db_session.commit()
    _completed_fixture(
        db_session,
        event_key=9303,
        winner="First Player",
        event_day=date(2026, 6, 12),
        scores=[
            {"score_first": "6", "score_second": "4", "score_set": "1"},
            {"score_first": "6", "score_second": "3", "score_set": "2"},
        ],  # total games = 10 + 9 = 19 -> Under 20.5 wins
    )

    settled = list_settled_published_tips(
        db_session, model_version=OVER_UNDER_GAMES_MODEL_VERSION
    )
    over_item = next(row for row in settled if row.id == tip_over.id)
    under_item = next(row for row in settled if row.id == tip_under.id)
    assert over_item.outcome == "lost"
    assert under_item.outcome == "won"


def test_over_under_games_pending_while_match_not_yet_finished(db_session):
    """Match still upcoming (no ``Fixture`` row yet): stays pending."""
    _publish(
        db_session,
        event_key=9304,
        selection="Over 20.5",
        odds=1.9,
        stake=1.0,
        edge=5.0,
        model_version=OVER_UNDER_GAMES_MODEL_VERSION,
        model_name="random_forest",
        event_day=date(2026, 6, 13),
    )

    settled = list_settled_published_tips(
        db_session, model_version=OVER_UNDER_GAMES_MODEL_VERSION
    )
    item = next(row for row in settled if row.event_key == 9304)
    assert item.outcome == "pending"


def test_over_under_games_void_when_finished_but_score_not_yet_available(db_session):
    _publish(
        db_session,
        event_key=9307,
        selection="Over 20.5",
        odds=1.9,
        stake=1.0,
        edge=5.0,
        model_version=OVER_UNDER_GAMES_MODEL_VERSION,
        model_name="random_forest",
        event_day=date(2026, 6, 13),
    )
    db_session.delete(
        db_session.scalar(select(NextFixture).where(NextFixture.event_key == 9307))
    )
    db_session.commit()
    _completed_fixture(
        db_session,
        event_key=9307,
        winner="First Player",
        event_day=date(2026, 6, 13),
        scores=None,
    )

    settled = list_settled_published_tips(
        db_session, model_version=OVER_UNDER_GAMES_MODEL_VERSION
    )
    item = next(row for row in settled if row.event_key == 9307)
    assert item.outcome == "void"


def test_extra_markets_void_on_cancelled_match(db_session):
    """Cancelled-without-winner matches must stay void for extra markets too
    (never pending forever, never a guessed loss)."""
    _publish(
        db_session,
        event_key=9305,
        selection="First Player",
        odds=1.9,
        stake=1.0,
        edge=5.0,
        model_version=FIRST_SET_WINNER_MODEL_VERSION,
        model_name="random_forest",
        event_day=date(2026, 6, 14),
    )
    db_session.delete(
        db_session.scalar(select(NextFixture).where(NextFixture.event_key == 9305))
    )
    db_session.commit()
    _cancelled_fixture(db_session, event_key=9305, event_day=date(2026, 6, 14))

    settled = list_settled_published_tips(
        db_session, model_version=FIRST_SET_WINNER_MODEL_VERSION
    )
    item = next(row for row in settled if row.event_key == 9305)
    assert item.outcome == "void"


def test_match_winner_archive_filter_and_official_play_population(db_session):
    _publish(
        db_session,
        event_key=9401,
        selection="Alice",
        odds=1.9,
        stake=1.0,
        edge=5.0,
        model_version="v3",
        official_play=False,
    )
    _publish(
        db_session,
        event_key=9402,
        selection="Alice",
        odds=1.9,
        stake=1.0,
        edge=5.0,
        model_version="v4",
        model_name="voting_ensemble",
        official_play=True,
        value_decision="PLAY",
    )

    active = compute_published_live_stats(
        db_session, market="match_winner", include_archived=False
    )
    assert active.predictions_total == 1
    assert active.include_archived is False

    historical = compute_published_live_stats(
        db_session, market="match_winner", include_archived=True
    )
    assert historical.predictions_total == 2

    official = compute_published_live_stats(
        db_session,
        market="match_winner",
        include_archived=False,
        official_only=True,
    )
    assert official.predictions_total == 1
    assert official.official_only is True


def test_clv_ignores_odds_from_a_different_market(db_session):
    event_key = 9410
    captured_at = datetime.now()
    _publish(
        db_session,
        event_key=event_key,
        selection="Alice",
        odds=None,
        stake=1.0,
        edge=None,
        model_version=FIRST_SET_WINNER_MODEL_VERSION,
        model_name="random_forest",
        market="first_set_winner",
    )
    _add_snapshot_pair(
        db_session,
        event_key=event_key,
        snapshot_type="closing",
        bookmaker="pinnacle",
        captured_at=captured_at,
        alice_odds=1.80,
        bob_odds=2.10,
        market="match_winner",
    )

    settled = list_settled_published_tips(
        db_session, market="first_set_winner", include_archived=True
    )
    item = next(row for row in settled if row.event_key == event_key)
    assert item.clv_available is False
    assert item.closing_odds is None
    assert item.publication_odds is None
