"""Tests for the read-only CLV summary (published_clv_summary / GET /clv-summary)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from backend.src.app.ml.prediction.extra_markets_predictor import (
    FIRST_SET_WINNER_MODEL_VERSION,
    OVER_UNDER_GAMES_MODEL_VERSION,
)
from backend.src.app.schemas.published_prediction import PublishedPredictionCreate
from backend.src.app.services.published_clv_summary import compute_published_clv_summary
from backend.src.app.services.published_live_stats import list_settled_published_tips
from backend.src.app.services.published_predictions import publish_prediction
from backend.src.entity.fixture import Fixture
from backend.src.entity.next_fixture import NextFixture
from backend.src.entity.prematch_odds_snapshot import PrematchOddsSnapshot

# Past match: 2026-06-01 16:00 Europe/Rome (CEST) = 14:00 UTC.
PAST_DAY = date(2026, 6, 1)
PAST_KICKOFF_UTC = datetime(2026, 6, 1, 14, 0, 0)
PUBLISHED_AT = datetime(2026, 6, 1, 8, 0, 0)

MODEL_BY_MARKET = {
    "match_winner": ("v3", "logistic_regression"),
    "first_set_winner": (FIRST_SET_WINNER_MODEL_VERSION, "random_forest"),
    "over_under_games": (OVER_UNDER_GAMES_MODEL_VERSION, "random_forest"),
}


def _publish(
    db_session,
    *,
    event_key: int,
    market: str,
    selection: str,
    odds: float | None,
    value_decision: str | None,
    official_play: bool = False,
    completed: bool = True,
) -> None:
    """Publish while the match is in the future, then (optionally) complete it."""
    db_session.add(
        NextFixture(
            event_key=event_key,
            event_date=date.today() + timedelta(days=3),
            event_time=time(14, 0),
            event_first_player="Alice",
            event_second_player="Bob",
            event_status="Not Started",
            is_completed=False,
        )
    )
    db_session.commit()
    model_version, model_name = MODEL_BY_MARKET[market]
    publish_prediction(
        db_session,
        PublishedPredictionCreate(
            event_key=event_key,
            market=market,
            value_decision=value_decision,
            official_play=official_play,
            selection=selection,
            model_version=model_version,
            model_name=model_name,
            probability=0.6,
            odds=odds,
            void_odds=1.6667,
            edge=5.0,
            publication_source="system",
            event_date=PAST_DAY if completed else date.today() + timedelta(days=3),
            player_1_name="Alice",
            player_2_name="Bob",
        ),
        published_at=PUBLISHED_AT if completed else None,
    )
    if not completed:
        return
    next_row = db_session.scalar(select(NextFixture).where(NextFixture.event_key == event_key))
    db_session.delete(next_row)
    db_session.add(
        Fixture(
            event_key=event_key,
            event_date=PAST_DAY,
            event_time=time(16, 0),
            event_first_player="Alice",
            event_second_player="Bob",
            event_winner="First Player",
            event_status="Finished",
            event_final_result="2 - 0",
        )
    )
    db_session.commit()


def _snapshot(
    db_session,
    *,
    event_key: int,
    selection: str,
    bookmaker: str,
    odds: float,
    captured_at: datetime,
    snapshot_type: str = "closing",
    market: str = "match_winner",
    market_line: float | None = None,
) -> None:
    db_session.add(
        PrematchOddsSnapshot(
            event_key=event_key,
            market=market,
            market_line=market_line,
            selection=selection,
            bookmaker=bookmaker,
            odds=odds,
            implied_probability=1 / odds,
            margin=0.0,
            captured_at=captured_at,
            source="test",
            snapshot_type=snapshot_type,
            detection_hash=(
                f"{event_key}-{market}-{market_line}-{snapshot_type}-{bookmaker}-"
                f"{selection}-{captured_at.isoformat()}"
            ),
        )
    )
    db_session.commit()


def _closing_pair(db_session, *, event_key: int, quotes: dict[str, tuple[float, float]],
                  captured_at: datetime, selections=("Alice", "Bob"),
                  market: str = "match_winner", market_line: float | None = None) -> None:
    for bookmaker, (first, second) in quotes.items():
        _snapshot(db_session, event_key=event_key, selection=selections[0], bookmaker=bookmaker,
                  odds=first, captured_at=captured_at, market=market, market_line=market_line)
        _snapshot(db_session, event_key=event_key, selection=selections[1], bookmaker=bookmaker,
                  odds=second, captured_at=captured_at, market=market, market_line=market_line)


def _seed_ledger(db_session) -> None:
    closing_at = PAST_KICKOFF_UTC - timedelta(minutes=5)
    # 1) Vincente PLAY: presa 2.00, closing media (1.80 + 1.90) / 2 = 1.85 -> +8.1081%.
    _publish(db_session, event_key=9501, market="match_winner", selection="Alice",
             odds=2.0, value_decision="PLAY", official_play=True)
    _snapshot(db_session, event_key=9501, selection="Alice", bookmaker="publication",
              odds=2.0, captured_at=PUBLISHED_AT, snapshot_type="publication")
    _closing_pair(db_session, event_key=9501,
                  quotes={"book_a": (1.80, 2.00), "book_b": (1.90, 1.90)},
                  captured_at=closing_at)
    # 2) Vincente PLAY: presa 1.50, closing 1.60 -> -6.25%.
    _publish(db_session, event_key=9502, market="match_winner", selection="Alice",
             odds=1.5, value_decision="PLAY", official_play=True)
    _closing_pair(db_session, event_key=9502, quotes={"book_a": (1.60, 2.30)},
                  captured_at=closing_at)
    # 3) Vincente PLAY: unica closing PRIMA della pubblicazione -> nessun CLV.
    _publish(db_session, event_key=9503, market="match_winner", selection="Alice",
             odds=1.9, value_decision="PLAY", official_play=True)
    _closing_pair(db_session, event_key=9503, quotes={"book_a": (1.85, 1.95)},
                  captured_at=PUBLISHED_AT - timedelta(hours=1))
    # 4) Vincente PLAY: closing solo per un nome diverso -> selection_not_in_closing.
    _publish(db_session, event_key=9504, market="match_winner", selection="Alice",
             odds=2.1, value_decision="PLAY", official_play=True)
    _closing_pair(db_session, event_key=9504, quotes={"book_a": (2.0, 1.8)},
                  captured_at=closing_at, selections=("A. Smith", "Bob"))
    # 5) O/U NO BET: presa 1.95, closing Over 20.5 = 2.05 -> -4.878%.
    _publish(db_session, event_key=9505, market="over_under_games", selection="Over 20.5",
             odds=1.95, value_decision="NO BET")
    _closing_pair(db_session, event_key=9505, quotes={"book_a": (2.05, 1.75)},
                  captured_at=closing_at, selections=("Over 20.5", "Under 20.5"),
                  market="over_under_games", market_line=20.5)
    # 6) O/U PLAY senza alcuna closing, partita finita -> no_closing_snapshot.
    _publish(db_session, event_key=9506, market="over_under_games", selection="Under 20.5",
             odds=1.9, value_decision="PLAY", official_play=True)
    # 7) 1° set senza quota pubblicata -> no_published_odds.
    _publish(db_session, event_key=9507, market="first_set_winner", selection="First Player",
             odds=None, value_decision=None)
    # 8) 1° set PLAY su partita futura, closing non ancora catturata -> awaiting_closing.
    _publish(db_session, event_key=9508, market="first_set_winner", selection="Second Player",
             odds=2.2, value_decision="PLAY", official_play=True, completed=False)


def test_clv_summary_by_market_and_decision(db_session):
    _seed_ledger(db_session)

    summary = compute_published_clv_summary(db_session)

    overall = summary.overall
    assert overall.predictions_total == 8
    assert overall.clv_count == 3
    assert overall.clv_missing == 5
    assert overall.missing_reasons == {
        "no_published_odds": 1,
        "awaiting_closing": 1,
        "closing_before_publication": 1,
        "selection_not_in_closing": 1,
        "no_closing_snapshot": 1,
    }
    assert overall.clv_eligible == 6
    assert overall.clv_coverage_eligible_pct == 50.0
    assert round(overall.clv_coverage_pct or 0.0, 4) == 37.5
    assert overall.clv_positive_count == 1
    assert round(overall.clv_median_pct or 0.0, 4) == -4.878
    assert overall.closing_basis_counts == {"consensus_avg": 3}

    by_market = {bucket.key: bucket for bucket in summary.by_market}
    assert list(by_market) == ["match_winner", "first_set_winner", "over_under_games"]
    match_winner = by_market["match_winner"]
    assert match_winner.predictions_total == 4
    assert match_winner.clv_count == 2
    assert round(match_winner.clv_avg_pct or 0.0, 4) == round(
        ((2.0 / 1.85 - 1) * 100 + (1.5 / 1.6 - 1) * 100) / 2, 4
    )
    assert match_winner.clv_positive_pct == 50.0
    assert by_market["first_set_winner"].clv_count == 0
    assert by_market["first_set_winner"].clv_eligible == 0
    assert by_market["first_set_winner"].clv_coverage_eligible_pct is None

    by_decision = {bucket.key: bucket for bucket in summary.by_decision}
    assert list(by_decision) == ["PLAY", "NO BET", "none"]
    assert by_decision["PLAY"].predictions_total == 6
    assert by_decision["PLAY"].clv_count == 2
    assert by_decision["NO BET"].clv_count == 1
    assert round(by_decision["NO BET"].clv_avg_pct or 0.0, 4) == round(
        (1.95 / 2.05 - 1) * 100, 4
    )

    keys = [bucket.key for bucket in summary.by_market_decision]
    assert keys == [
        "match_winner|PLAY",
        "first_set_winner|PLAY",
        "first_set_winner|none",
        "over_under_games|PLAY",
        "over_under_games|NO BET",
    ]
    assert "quota_presa / quota_closing - 1" in summary.clv_formula


def test_clv_no_vig_variant_uses_closing_fair_probability(db_session):
    _seed_ledger(db_session)

    item = next(
        row for row in list_settled_published_tips(db_session) if row.event_key == 9501
    )
    fair = (1 / 1.85) / ((1 / 1.85) + (1 / 1.95))
    assert round(item.clv_no_vig_pct or 0.0, 4) == round((2.0 * fair - 1) * 100, 4)
    assert item.clv_missing_reason is None

    missing = next(
        row for row in list_settled_published_tips(db_session) if row.event_key == 9503
    )
    assert missing.clv_pct is None
    assert missing.clv_missing_reason == "closing_before_publication"


def test_clv_summary_official_only_keeps_only_official_plays(db_session):
    _seed_ledger(db_session)

    summary = compute_published_clv_summary(db_session, official_only=True)

    assert summary.official_only is True
    assert summary.overall.predictions_total == 6
    assert [bucket.key for bucket in summary.by_decision] == ["PLAY"]


def test_clv_summary_endpoint(client, auth_headers, db_session):
    _seed_ledger(db_session)

    response = client.get(
        "/api/published-predictions/clv-summary",
        params={"market": "match_winner"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["market"] == "match_winner"
    assert body["overall"]["predictions_total"] == 4
    assert body["overall"]["clv_count"] == 2
    assert [bucket["key"] for bucket in body["by_market_decision"]] == ["match_winner|PLAY"]
    assert body["overall"]["missing_reasons"]["closing_before_publication"] == 1


def test_clv_summary_endpoint_requires_admin(client):
    response = client.get("/api/published-predictions/clv-summary")
    assert response.status_code in {401, 403}
