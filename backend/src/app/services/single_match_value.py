from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.odds_builder import (
    FixtureOddsRecord,
    MatchWinnerOddsAverage,
    average_match_winner_odds_from_record,
    bookmaker_margin,
    profit_for_unit_stake,
)
from backend.src.app.ml.model_versioning import ModelVersion
from backend.src.app.models import Fixture, MatchPrediction, NextFixture
from backend.src.app.schemas.single_match_value import (
    SingleMatchValueDecision,
    SingleMatchValueItem,
    SingleMatchValueResponse,
    SingleMatchValueSimulation,
    SingleMatchValueSimulationBucket,
    SingleMatchValueSummary,
)
from backend.src.app.services.predictions import (
    COMPLETED_WINNERS,
    PLAYED_DAYS_BACK,
    UPCOMING_DAYS_FORWARD,
    FixturePredictionStatus,
    PredictionOutcome,
    _predictions_by_event_key_with_fallback,
    _resolve_model_name,
    list_next_fixtures,
    list_played_fixtures_with_predictions,
)

SINGLE_MATCH_STAKE = 1.0
MATCH_WINNER_MARKET_LABEL = "Vincente match"
DEFAULT_MIN_EDGE_PERCENT = 2.0
MIN_EDGE_PERCENT_FLOOR = 1.0
MIN_EDGE_PERCENT_CAP = 10.0
LOW_BOOKMAKER_COUNT_THRESHOLD = 2
LOW_BOOKMAKER_COUNT_PENALTY = 0.5


@dataclass(frozen=True)
class SingleMatchContext:
    fixture: NextFixture | Fixture
    prediction: MatchPrediction | None
    odds: MatchWinnerOddsAverage | None
    actual_winner: str | None = None


def calculate_void_odds(model_probability: float) -> float:
    if model_probability <= 0 or model_probability > 1:
        raise ValueError("model_probability must be in the range (0, 1].")
    return 1.0 / model_probability


def calculate_expected_roi(market_odds: float, model_probability: float) -> float:
    return market_odds * model_probability - 1.0


def calculate_match_min_edge_percent(
    player_1_odd: float,
    player_2_odd: float,
    *,
    bookmaker_count: int | None = None,
) -> float:
    """Per-match safety margin above void odds, derived from market overround."""
    try:
        margin_pct = bookmaker_margin(player_1_odd, player_2_odd) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return DEFAULT_MIN_EDGE_PERCENT

    suggested = max(MIN_EDGE_PERCENT_FLOOR, min(MIN_EDGE_PERCENT_CAP, margin_pct))
    if bookmaker_count is not None and bookmaker_count < LOW_BOOKMAKER_COUNT_THRESHOLD:
        suggested = min(MIN_EDGE_PERCENT_CAP, suggested + LOW_BOOKMAKER_COUNT_PENALTY)
    return round(suggested, 2)


def classify_single_bet_value(
    *,
    market_odds: float,
    void_odds: float,
    min_edge_percent: float,
) -> SingleMatchValueDecision:
    min_edge_fraction = min_edge_percent / 100.0
    play_threshold = void_odds * (1.0 + min_edge_fraction)
    if market_odds >= play_threshold:
        return "PLAY"
    if market_odds < void_odds:
        return "NO BET"
    return "BORDERLINE"


def analyze_single_match_value(
    *,
    match_id: int,
    event_date: date | None,
    event_time,
    tournament_name: str | None,
    player_a: str | None,
    player_b: str | None,
    predicted_winner: str,
    prob_player_1_win: float,
    odds: MatchWinnerOddsAverage,
    min_edge_percent: float | None = None,
    actual_winner: str | None = None,
) -> SingleMatchValueItem | None:
    model_probability = _model_prob_for_selection(predicted_winner, prob_player_1_win)
    market_odds = _market_odds_for_selection(predicted_winner, odds)
    if model_probability is None or market_odds is None:
        return None

    suggested_min_edge_percent = (
        float(min_edge_percent)
        if min_edge_percent is not None
        else DEFAULT_MIN_EDGE_PERCENT
    )
    effective_min_edge_percent = suggested_min_edge_percent

    void_odds = calculate_void_odds(model_probability)
    edge_absolute = market_odds - void_odds
    edge_percent = (edge_absolute / void_odds) * 100.0
    expected_roi = calculate_expected_roi(market_odds, model_probability)
    decision = classify_single_bet_value(
        market_odds=market_odds,
        void_odds=void_odds,
        min_edge_percent=effective_min_edge_percent,
    )
    is_correct = None
    profit_loss = None
    if actual_winner in COMPLETED_WINNERS:
        is_correct = predicted_winner == actual_winner
        profit_loss = profit_for_unit_stake(market_odds, won=is_correct)

    return SingleMatchValueItem(
        match_id=match_id,
        event_date=event_date,
        event_time=event_time,
        tournament_name=tournament_name,
        competition=tournament_name,
        player_a=player_a,
        player_b=player_b,
        market=MATCH_WINNER_MARKET_LABEL,
        selection=_winner_label(predicted_winner, player_a, player_b),
        selection_code=predicted_winner,
        model_probability=round(model_probability, 6),
        market_odds=round(market_odds, 4),
        void_odds=round(void_odds, 4),
        edge_absolute=round(edge_absolute, 4),
        edge_percent=round(edge_percent, 2),
        expected_roi=round(expected_roi, 6),
        suggested_min_edge_percent=suggested_min_edge_percent,
        min_edge_percent=round(effective_min_edge_percent, 2),
        stake=SINGLE_MATCH_STAKE,
        decision=decision,
        value_label=_value_label(decision),
        edge_label=_edge_label(decision, expected_roi),
        explanation=_explanation(decision),
        bookmaker_count=odds.odds_bookmaker_count,
        actual_winner=actual_winner,
        is_correct=is_correct,
        profit_loss=round(profit_loss, 4) if profit_loss is not None else None,
    )


def get_single_match_value_analysis(
    db: Session,
    *,
    model_version: ModelVersion = "v2",
    model_name: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
    status: FixturePredictionStatus = "upcoming",
    outcome: PredictionOutcome = "all",
    player_name: str | None = None,
    min_edge_percent: float | None = DEFAULT_MIN_EDGE_PERCENT,
    min_edge_overrides: dict[int, float] | None = None,
) -> SingleMatchValueResponse:
    selected_model_name = _resolve_model_name(model_version, model_name)
    baseline_min_edge = (
        DEFAULT_MIN_EDGE_PERCENT if min_edge_percent is None else float(min_edge_percent)
    )
    #region agent log
    try:
        import json as _json
        from pathlib import Path as _Path
        from datetime import datetime as _dt
        _Path(r"c:\Users\trott\git\tennis_oracle\debug-839b99.log").open("a", encoding="utf-8").write(
            _json.dumps({
                "sessionId": "839b99",
                "runId": "pre-fix",
                "hypothesisId": "B",
                "location": "single_match_value.py:get_single_match_value_analysis",
                "message": "server received min_edge_percent",
                "data": {
                    "min_edge_percent_arg": min_edge_percent,
                    "baseline_min_edge": baseline_min_edge,
                    "is_none": min_edge_percent is None,
                    "model_version": model_version,
                    "model_name": model_name,
                    "status": status,
                },
                "timestamp": int(_dt.now().timestamp() * 1000),
            }) + "\n"
        )
    except Exception:
        pass
    #endregion
    contexts = _single_match_contexts(
        db,
        model_version=model_version,
        model_name=selected_model_name,
        from_date=from_date,
        to_date=to_date,
        status=status,
        outcome=outcome,
        player_name=player_name,
    )
    overrides = min_edge_overrides or {}
    items = [
        item
        for context in contexts
        if (
            item := _analyze_context(
                context,
                min_edge_percent=overrides.get(
                    context.fixture.event_key,
                    baseline_min_edge,
                ),
            )
        )
        is not None
    ]

    page_items = items[offset : offset + limit]
    return SingleMatchValueResponse(
        model_version=model_version,
        model_name=selected_model_name,
        min_edge_percent=baseline_min_edge,
        items=page_items,
        total=len(items),
        offset=offset,
        limit=limit,
        summary=_summary(items),
        simulation=_simulation(items),
        warnings=[],
    )


def _single_match_contexts(
    db: Session,
    *,
    model_version: ModelVersion,
    model_name: str | None,
    from_date: date | None,
    to_date: date | None,
    status: FixturePredictionStatus,
    outcome: PredictionOutcome,
    player_name: str | None,
) -> list[SingleMatchContext]:
    today = date.today()
    contexts: list[SingleMatchContext] = []

    if status in {"upcoming", "all"}:
        upcoming_from = from_date or today
        upcoming_to = to_date or today + timedelta(days=UPCOMING_DAYS_FORWARD)
        fixtures = list_next_fixtures(
            db,
            from_date=upcoming_from,
            to_date=upcoming_to,
            limit=1000,
            offset=0,
            player_name=player_name,
            odds_required=True,
        )
        predictions = _predictions_by_event_key_with_fallback(
            db,
            [fixture.event_key for fixture in fixtures],
            model_version,
            model_name,
        )
        contexts.extend(
            SingleMatchContext(
                fixture=fixture,
                prediction=predictions.get(fixture.event_key),
                odds=_odds_for_fixture(fixture),
            )
            for fixture in fixtures
        )

    if status in {"played", "all"}:
        played_from = from_date or today - timedelta(days=PLAYED_DAYS_BACK)
        played_to = to_date or today
        played_rows = list_played_fixtures_with_predictions(
            db,
            model_version=model_version,
            explicit_model_name=model_name,
            from_date=played_from,
            to_date=played_to,
            outcome=outcome,
            limit=1000,
            offset=0,
            player_name=player_name,
            odds_required=True,
        )
        contexts.extend(
            SingleMatchContext(
                fixture=fixture,
                prediction=prediction,
                odds=_odds_for_fixture(fixture),
                actual_winner=fixture.event_winner,
            )
            for fixture, prediction in played_rows
        )

    return contexts


def _analyze_context(
    context: SingleMatchContext,
    *,
    min_edge_percent: float | None,
) -> SingleMatchValueItem | None:
    fixture = context.fixture
    prediction = context.prediction
    if prediction is None or prediction.predicted_winner not in COMPLETED_WINNERS:
        return None
    if prediction.prob_player_1_win is None or context.odds is None:
        return None

    return analyze_single_match_value(
        match_id=fixture.event_key,
        event_date=fixture.event_date,
        event_time=fixture.event_time,
        tournament_name=fixture.tournament_name,
        player_a=fixture.event_first_player,
        player_b=fixture.event_second_player,
        predicted_winner=prediction.predicted_winner,
        prob_player_1_win=prediction.prob_player_1_win,
        odds=context.odds,
        min_edge_percent=min_edge_percent,
        actual_winner=prediction.actual_winner or context.actual_winner,
    )


def _odds_for_fixture(fixture: NextFixture | Fixture) -> MatchWinnerOddsAverage | None:
    return average_match_winner_odds_from_record(
        FixtureOddsRecord(
            match_id=fixture.event_key,
            match_date=fixture.event_date,
            player_1_id=fixture.first_player_key,
            player_2_id=fixture.second_player_key,
            player_1_name=fixture.event_first_player,
            player_2_name=fixture.event_second_player,
            odds=fixture.odds,
            event_live=getattr(fixture, "event_live", None),
        )
    )


def _model_prob_for_selection(
    predicted_winner: str,
    prob_player_1_win: float,
) -> float | None:
    if predicted_winner == "First Player":
        return prob_player_1_win
    if predicted_winner == "Second Player":
        return 1.0 - prob_player_1_win
    return None


def _market_odds_for_selection(
    predicted_winner: str,
    odds: MatchWinnerOddsAverage,
) -> float | None:
    if predicted_winner == "First Player":
        return odds.avg_player_1_odds
    if predicted_winner == "Second Player":
        return odds.avg_player_2_odds
    return None


def _winner_label(
    predicted_winner: str,
    player_1_name: str | None,
    player_2_name: str | None,
) -> str:
    if predicted_winner == "First Player":
        return player_1_name or "Player 1"
    if predicted_winner == "Second Player":
        return player_2_name or "Player 2"
    return predicted_winner


def _value_label(decision: SingleMatchValueDecision) -> str:
    if decision == "PLAY":
        return "Singola con valore"
    if decision == "BORDERLINE":
        return "Quota in area void"
    return "Quota sotto valore"


def _edge_label(decision: SingleMatchValueDecision, expected_roi: float) -> str:
    if decision == "PLAY":
        return "Valore reale intercettato"
    if expected_roi < 0:
        return "Quota troppo bassa per essere profittevole"
    return "Margine positivo ma non sufficiente"


def _explanation(decision: SingleMatchValueDecision) -> str:
    if decision == "PLAY":
        return (
            "La quota mercato supera la quota void con il margine di sicurezza richiesto: "
            "secondo la probabilita AI, la singola ha valore positivo nel lungo periodo."
        )
    if decision == "BORDERLINE":
        return (
            "La quota mercato e sopra la quota void, ma il margine e troppo sottile: "
            "area void, da trattare con prudenza."
        )
    return (
        "Giocata sconsigliata anche se probabile: la quota offerta e sotto la quota void "
        "e nel lungo periodo non paga abbastanza il rischio."
    )


def _summary(items: list[SingleMatchValueItem]) -> SingleMatchValueSummary:
    return SingleMatchValueSummary(
        total=len(items),
        play_count=sum(item.decision == "PLAY" for item in items),
        no_bet_count=sum(item.decision == "NO BET" for item in items),
        borderline_count=sum(item.decision == "BORDERLINE" for item in items),
        avg_market_odds=_avg([item.market_odds for item in items]),
        avg_void_odds=_avg([item.void_odds for item in items]),
        avg_expected_roi=_avg([item.expected_roi for item in items]),
    )


def _simulation(items: list[SingleMatchValueItem]) -> SingleMatchValueSimulation:
    play_items = [item for item in items if item.decision == "PLAY"]
    above_void = [item for item in items if item.edge_absolute >= 0]
    below_void = [item for item in items if item.edge_absolute < 0]
    return SingleMatchValueSimulation(
        stake=SINGLE_MATCH_STAKE,
        play_bets=_simulation_bucket(play_items),
        above_void=_simulation_bucket(above_void),
        below_void=_simulation_bucket(below_void),
        borderline_count=sum(item.decision == "BORDERLINE" for item in items),
    )


def _simulation_bucket(items: list[SingleMatchValueItem]) -> SingleMatchValueSimulationBucket:
    resolved = [item for item in items if item.profit_loss is not None]
    profit = sum(item.profit_loss or 0.0 for item in resolved)
    return SingleMatchValueSimulationBucket(
        bets_count=len(items),
        resolved_count=len(resolved),
        profit_loss_units=round(profit, 4),
        roi_pct=round((profit / len(resolved)) * 100.0, 2) if resolved else None,
        hit_rate_pct=round(
            (sum(item.is_correct is True for item in resolved) / len(resolved)) * 100.0,
            2,
        )
        if resolved
        else None,
        avg_market_odds=_avg([item.market_odds for item in items]),
        avg_void_odds=_avg([item.void_odds for item in items]),
    )


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)
