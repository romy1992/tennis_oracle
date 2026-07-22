from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.odds_builder import (
    FixtureOddsRecord,
    MatchWinnerOddsAverage,
    average_match_winner_odds_from_record,
)
from backend.src.app.ml.model_selection import select_best_model
from backend.src.app.ml.model_versioning import ModelVersion
from backend.src.app.models import Fixture, MatchPrediction, NextFixture
from backend.src.app.schemas.prediction import (
    DailyPredictionStatsDay,
    DailyPredictionStatsResponse,
    FixturesWithPredictionsPage,
    MatchPredictionRead,
    NextFixtureRead,
    NextFixtureWithPrediction,
    PredictionModelBreakdown,
    PredictionSummaryResponse,
)
from backend.src.app.services.match_lifecycle import (
    COMPLETED_WINNERS,
    classify_match_lifecycle,
    match_lifecycle_label,
    settle_simulated_bet,
)

FixturePredictionStatus = Literal["upcoming", "played", "all"]
PredictionOutcome = Literal["all", "won", "lost"]
UPCOMING_DAYS_FORWARD = 10
PLAYED_DAYS_BACK = 30


def _player_name_filter(
    player_name: str | None,
    first_player_column,
    second_player_column,
):
    if not player_name:
        return []
    needle = f"%{player_name.strip()}%"
    return [
        or_(
            first_player_column.ilike(needle),
            second_player_column.ilike(needle),
        )
    ]


@dataclass(frozen=True)
class PredictionOddsStats:
    predictions_with_odds: int
    avg_predicted_winner_odds: float | None
    avg_winning_odds: float | None
    theoretical_profit_units: float
    theoretical_roi_pct: float | None


def _next_fixture_filters(
    from_date: date | None,
    to_date: date | None,
    player_name: str | None = None,
    odds_required: bool = False,
):
    filters = [NextFixture.is_completed.is_(False)]
    if from_date is not None:
        filters.append(NextFixture.event_date >= from_date)
    if to_date is not None:
        filters.append(NextFixture.event_date <= to_date)
    filters.extend(
        _player_name_filter(
            player_name,
            NextFixture.event_first_player,
            NextFixture.event_second_player,
        )
    )
    if odds_required:
        filters.append(NextFixture.odds.is_not(None))
    return filters


def count_next_fixtures(
    db: Session,
    from_date: date | None = None,
    to_date: date | None = None,
    player_name: str | None = None,
    odds_required: bool = False,
) -> int:
    stmt = select(func.count()).select_from(NextFixture).where(
        *_next_fixture_filters(from_date, to_date, player_name, odds_required)
    )
    return int(db.scalar(stmt) or 0)


def list_next_fixtures(
    db: Session,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 100,
    offset: int = 0,
    player_name: str | None = None,
    odds_required: bool = False,
) -> list[NextFixture]:
    stmt = (
        select(NextFixture)
        .where(*_next_fixture_filters(from_date, to_date, player_name, odds_required))
        .order_by(
            NextFixture.event_date.asc().nullslast(),
            NextFixture.event_time.asc().nullslast(),
            NextFixture.event_key.asc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def _confidence(prob_player_1_win: float | None) -> float | None:
    if prob_player_1_win is None:
        return None
    return max(prob_player_1_win, 1.0 - prob_player_1_win)


def _prediction_read(
    prediction: MatchPrediction,
    odds: MatchWinnerOddsAverage | None = None,
    actual_winner: str | None = None,
) -> MatchPredictionRead:
    resolved_winner = prediction.actual_winner or actual_winner
    is_correct = None
    if resolved_winner is not None and prediction.predicted_winner is not None:
        is_correct = prediction.predicted_winner == resolved_winner

    return MatchPredictionRead(
        event_key=prediction.event_key,
        model_version=prediction.model_version,
        model_name=prediction.model_name,
        predicted_at=prediction.predicted_at,
        prob_player_1_win=prediction.prob_player_1_win,
        predicted_winner=prediction.predicted_winner,
        actual_winner=resolved_winner,
        is_correct=is_correct,
        predicted_winner_odds=_predicted_winner_odds(prediction.predicted_winner, odds),
        odds_bookmaker_count=odds.odds_bookmaker_count if odds is not None else None,
        confidence=_confidence(prediction.prob_player_1_win),
        warnings=[],
    )


def _event_date_for_prediction(db: Session, event_key: int) -> date | None:
    next_fixture = db.scalar(
        select(NextFixture.event_date).where(NextFixture.event_key == event_key)
    )
    if next_fixture:
        return next_fixture
    return db.scalar(select(Fixture.event_date).where(Fixture.event_key == event_key))


def _next_fixture_odds(fixture: NextFixture) -> MatchWinnerOddsAverage | None:
    return average_match_winner_odds_from_record(
        FixtureOddsRecord(
            match_id=fixture.event_key,
            match_date=fixture.event_date,
            player_1_id=fixture.first_player_key,
            player_2_id=fixture.second_player_key,
            player_1_name=fixture.event_first_player,
            player_2_name=fixture.event_second_player,
            odds=fixture.odds,
        )
    )


def _fixture_odds(fixture: Fixture) -> MatchWinnerOddsAverage | None:
    return average_match_winner_odds_from_record(
        FixtureOddsRecord(
            match_id=fixture.event_key,
            match_date=fixture.event_date,
            player_1_id=fixture.first_player_key,
            player_2_id=fixture.second_player_key,
            player_1_name=fixture.event_first_player,
            player_2_name=fixture.event_second_player,
            odds=fixture.odds,
            event_live=fixture.event_live,
        )
    )


def _fixture_read_from_completed_fixture(fixture: Fixture) -> NextFixtureRead:
    return NextFixtureRead(
        id=fixture.id_fixture,
        event_key=fixture.event_key,
        event_date=fixture.event_date,
        event_time=fixture.event_time,
        event_first_player=fixture.event_first_player,
        first_player_key=fixture.first_player_key,
        event_second_player=fixture.event_second_player,
        second_player_key=fixture.second_player_key,
        tournament_name=fixture.tournament_name,
        tournament_key=fixture.tournament_key,
        tournament_round=fixture.tournament_round,
        surface=None,
        event_status=fixture.event_status,
        event_type_type=fixture.event_type_type,
        odds=fixture.odds,
        imported_at=None,
        week_start=None,
        week_end=None,
        source="api-tennis",
        is_completed=True,
        moved_to_fixture_at=None,
    )


def _predicted_winner_odds(
    predicted_winner: str | None,
    odds: MatchWinnerOddsAverage | None,
) -> float | None:
    if odds is None:
        return None
    if predicted_winner == "First Player":
        return odds.avg_player_1_odds
    if predicted_winner == "Second Player":
        return odds.avg_player_2_odds
    return None


def _resolve_model_name(
    model_version: ModelVersion,
    model_name: str | None,
) -> str | None:
    if model_name is not None:
        return model_name
    try:
        return select_best_model(model_version).model_name
    except (FileNotFoundError, ValueError):
        return None


def _played_outcome_filters(outcome: PredictionOutcome):
    if outcome == "won":
        return [MatchPrediction.predicted_winner == Fixture.event_winner]
    if outcome == "lost":
        return [
            MatchPrediction.predicted_winner.isnot(None),
            MatchPrediction.predicted_winner != Fixture.event_winner,
        ]
    return []


def _played_fixture_filters(
    from_date: date | None,
    to_date: date | None,
    player_name: str | None = None,
    odds_required: bool = False,
):
    filters = [Fixture.event_winner.in_(COMPLETED_WINNERS)]
    filters.extend(_played_date_filters(from_date, to_date))
    filters.extend(
        _player_name_filter(
            player_name,
            Fixture.event_first_player,
            Fixture.event_second_player,
        )
    )
    if odds_required:
        filters.append(Fixture.odds.is_not(None))
    return filters


def _played_prediction_exists_filter(
    model_version: ModelVersion,
    explicit_model_name: str | None,
    outcome: PredictionOutcome,
):
    if outcome == "all":
        return None

    conditions = [
        MatchPrediction.event_key == Fixture.event_key,
        MatchPrediction.model_version == model_version,
        MatchPrediction.predicted_winner.isnot(None),
        *_played_outcome_filters(outcome),
    ]
    if explicit_model_name is not None:
        conditions.append(MatchPrediction.model_name == explicit_model_name)

    return exists(select(1).where(*conditions))


def _played_date_bounds(
    status: FixturePredictionStatus,
    today: date,
    from_date: date | None,
    to_date: date | None,
) -> tuple[date | None, date | None]:
    if status not in {"played", "all"}:
        return from_date, to_date
    resolved_from = from_date if from_date is not None else today - timedelta(days=PLAYED_DAYS_BACK)
    resolved_to = to_date if to_date is not None else today
    return resolved_from, resolved_to


def _played_date_filters(from_date: date | None, to_date: date | None):
    filters = []
    if from_date is not None:
        filters.append(Fixture.event_date >= from_date)
    if to_date is not None:
        filters.append(Fixture.event_date <= to_date)
    return filters


def _played_base_filters(
    model_version: ModelVersion,
    explicit_model_name: str | None,
    from_date: date | None,
    to_date: date | None,
    outcome: PredictionOutcome,
    player_name: str | None = None,
    odds_required: bool = False,
):
    filters = [
        *_played_fixture_filters(from_date, to_date, player_name, odds_required),
    ]
    outcome_exists = _played_prediction_exists_filter(
        model_version,
        explicit_model_name,
        outcome,
    )
    if outcome_exists is not None:
        filters.append(outcome_exists)
    return filters


def count_played_fixtures(
    db: Session,
    *,
    model_version: ModelVersion,
    explicit_model_name: str | None,
    from_date: date | None = None,
    to_date: date | None = None,
    outcome: PredictionOutcome = "all",
    player_name: str | None = None,
    odds_required: bool = False,
) -> int:
    stmt = select(func.count()).select_from(Fixture).where(
        *_played_base_filters(
            model_version,
            explicit_model_name,
            from_date,
            to_date,
            outcome,
            player_name,
            odds_required,
        )
    )
    return int(db.scalar(stmt) or 0)


def _played_has_prediction_expr(
    model_version: ModelVersion,
    explicit_model_name: str | None,
):
    conditions = [
        MatchPrediction.event_key == Fixture.event_key,
        MatchPrediction.model_version == model_version,
        MatchPrediction.predicted_winner.isnot(None),
    ]
    if explicit_model_name is not None:
        conditions.append(MatchPrediction.model_name == explicit_model_name)
    return exists(select(1).where(*conditions))


def list_played_fixtures(
    db: Session,
    *,
    model_version: ModelVersion,
    explicit_model_name: str | None,
    from_date: date | None = None,
    to_date: date | None = None,
    outcome: PredictionOutcome = "all",
    limit: int = 100,
    offset: int = 0,
    player_name: str | None = None,
    odds_required: bool = False,
) -> list[Fixture]:
    has_prediction = _played_has_prediction_expr(model_version, explicit_model_name)
    stmt = (
        select(Fixture)
        .where(
            *_played_base_filters(
                model_version,
                explicit_model_name,
                from_date,
                to_date,
                outcome,
                player_name,
                odds_required,
            )
        )
        .order_by(
            # Prefer rows with a stored prediction so "Giocate" page 1 is useful.
            has_prediction.desc(),
            Fixture.event_date.desc().nullslast(),
            Fixture.event_time.desc().nullslast(),
            Fixture.event_key.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def list_played_fixtures_with_predictions(
    db: Session,
    *,
    model_version: ModelVersion,
    explicit_model_name: str | None,
    from_date: date | None = None,
    to_date: date | None = None,
    outcome: PredictionOutcome = "all",
    limit: int = 100,
    offset: int = 0,
    player_name: str | None = None,
    odds_required: bool = False,
) -> list[tuple[Fixture, MatchPrediction | None]]:
    fixtures = list_played_fixtures(
        db,
        model_version=model_version,
        explicit_model_name=explicit_model_name,
        from_date=from_date,
        to_date=to_date,
        outcome=outcome,
        limit=limit,
        offset=offset,
        player_name=player_name,
        odds_required=odds_required,
    )
    if not fixtures:
        return []

    selected_model_name = explicit_model_name or _resolve_model_name(
        model_version,
        None,
    )
    prediction_by_key = _predictions_by_event_key_with_fallback(
        db,
        [fixture.event_key for fixture in fixtures],
        model_version,
        selected_model_name,
    )
    return [
        (fixture, prediction_by_key.get(fixture.event_key))
        for fixture in fixtures
    ]


def _upcoming_date_bounds(
    status: FixturePredictionStatus,
    today: date,
    from_date: date | None,
    to_date: date | None,
) -> tuple[date | None, date | None]:
    if status not in {"upcoming", "all"}:
        return from_date, to_date
    resolved_from = from_date if from_date is not None else today
    resolved_to = (
        to_date
        if to_date is not None
        else today + timedelta(days=UPCOMING_DAYS_FORWARD)
    )
    return resolved_from, resolved_to


def _predictions_by_event_key(
    db: Session,
    event_keys: list[int],
    model_version: ModelVersion,
    selected_model_name: str | None,
) -> dict[int, MatchPrediction]:
    if not event_keys:
        return {}

    prediction_stmt = (
        select(MatchPrediction)
        .where(
            MatchPrediction.event_key.in_(event_keys),
            MatchPrediction.model_version == model_version,
        )
        .order_by(MatchPrediction.predicted_at.desc())
    )
    if selected_model_name is not None:
        prediction_stmt = prediction_stmt.where(MatchPrediction.model_name == selected_model_name)

    prediction_by_key: dict[int, MatchPrediction] = {}
    for prediction in db.scalars(prediction_stmt).all():
        prediction_by_key.setdefault(prediction.event_key, prediction)
    return prediction_by_key


def _predictions_by_event_key_with_fallback(
    db: Session,
    event_keys: list[int],
    model_version: ModelVersion,
    preferred_model_name: str | None,
) -> dict[int, MatchPrediction]:
    prediction_by_key = _predictions_by_event_key(
        db,
        event_keys,
        model_version,
        preferred_model_name,
    )
    if preferred_model_name is None:
        return prediction_by_key

    missing_keys = [event_key for event_key in event_keys if event_key not in prediction_by_key]
    if not missing_keys:
        return prediction_by_key

    fallback_predictions = _predictions_by_event_key(
        db,
        missing_keys,
        model_version,
        None,
    )
    for event_key, prediction in fallback_predictions.items():
        prediction_by_key.setdefault(event_key, prediction)
    return prediction_by_key


def _attach_lifecycle_fields(
    base: NextFixtureRead,
    *,
    event_winner: str | None = None,
    event_final_result: str | None = None,
    event_live: str | None = None,
) -> NextFixtureRead:
    lifecycle = classify_match_lifecycle(
        event_status=base.event_status,
        event_winner=event_winner,
        event_final_result=event_final_result,
        event_live=event_live,
        is_completed=base.is_completed,
    )
    return base.model_copy(
        update={
            "match_lifecycle_status": lifecycle,
            "match_lifecycle_label": match_lifecycle_label(lifecycle),
        }
    )


def _wrap_upcoming_fixture(
    fixture: NextFixture,
    stored_prediction: MatchPrediction | None,
) -> NextFixtureWithPrediction:
    fixture_odds = _next_fixture_odds(fixture)
    prediction = (
        _prediction_read(stored_prediction, fixture_odds) if stored_prediction else None
    )
    base = _attach_lifecycle_fields(NextFixtureRead.model_validate(fixture))
    return NextFixtureWithPrediction(
        **base.model_dump(),
        prediction=prediction,
        prediction_warning=None if prediction is not None else "missing_persisted_prediction",
    )


def _wrap_played_fixture(
    fixture: Fixture,
    stored_prediction: MatchPrediction | None,
) -> NextFixtureWithPrediction:
    fixture_odds = _fixture_odds(fixture)
    base = _attach_lifecycle_fields(
        _fixture_read_from_completed_fixture(fixture),
        event_winner=fixture.event_winner,
        event_final_result=fixture.event_final_result,
        event_live=fixture.event_live,
    )
    if stored_prediction is None:
        return NextFixtureWithPrediction(
            **base.model_dump(),
            prediction=None,
            prediction_warning="missing_persisted_prediction",
        )
    return NextFixtureWithPrediction(
        **base.model_dump(),
        prediction=_prediction_read(
            stored_prediction,
            fixture_odds,
            actual_winner=fixture.event_winner,
        ),
        prediction_warning=None,
    )


def get_next_fixtures_with_predictions(
    db: Session,
    model_version: ModelVersion = "v2",
    model_name: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 100,
    offset: int = 0,
    status: FixturePredictionStatus = "upcoming",
    outcome: PredictionOutcome = "all",
    player_name: str | None = None,
) -> FixturesWithPredictionsPage:
    today = date.today()
    odds_required = model_version == "v3"
    upcoming_from, upcoming_to = _upcoming_date_bounds(status, today, from_date, to_date)
    played_from, played_to = _played_date_bounds(status, today, from_date, to_date)

    upcoming_model_name = _resolve_model_name(model_version, model_name)
    played_model_name = upcoming_model_name
    results: list[NextFixtureWithPrediction] = []

    if status == "upcoming":
        total = count_next_fixtures(
            db,
            from_date=upcoming_from,
            to_date=upcoming_to,
            player_name=player_name,
            odds_required=odds_required,
        )
        fixtures = list_next_fixtures(
            db=db,
            from_date=upcoming_from,
            to_date=upcoming_to,
            limit=limit,
            offset=offset,
            player_name=player_name,
            odds_required=odds_required,
        )
        prediction_by_key = _predictions_by_event_key_with_fallback(
            db,
            [fixture.event_key for fixture in fixtures],
            model_version,
            upcoming_model_name,
        )
        results = [
            _wrap_upcoming_fixture(fixture, prediction_by_key.get(fixture.event_key))
            for fixture in fixtures
        ]
    elif status == "played":
        total = count_played_fixtures(
            db,
            model_version=model_version,
            explicit_model_name=played_model_name,
            from_date=played_from,
            to_date=played_to,
            outcome=outcome,
            player_name=player_name,
            odds_required=odds_required,
        )
        played_rows = list_played_fixtures_with_predictions(
            db,
            model_version=model_version,
            explicit_model_name=played_model_name,
            from_date=played_from,
            to_date=played_to,
            outcome=outcome,
            limit=limit,
            offset=offset,
            player_name=player_name,
            odds_required=odds_required,
        )
        results = [
            _wrap_played_fixture(fixture, stored_prediction)
            for fixture, stored_prediction in played_rows
        ]
    else:
        upcoming_total = count_next_fixtures(
            db,
            from_date=upcoming_from,
            to_date=upcoming_to,
            player_name=player_name,
            odds_required=odds_required,
        )
        played_total = count_played_fixtures(
            db,
            model_version=model_version,
            explicit_model_name=played_model_name,
            from_date=played_from,
            to_date=played_to,
            outcome=outcome if outcome != "all" else "all",
            player_name=player_name,
            odds_required=odds_required,
        )
        total = upcoming_total + played_total

        if offset < upcoming_total:
            upcoming_limit = min(limit, upcoming_total - offset)
            fixtures = list_next_fixtures(
                db=db,
                from_date=upcoming_from,
                to_date=upcoming_to,
                limit=upcoming_limit,
                offset=offset,
                player_name=player_name,
                odds_required=odds_required,
            )
            prediction_by_key = _predictions_by_event_key_with_fallback(
                db,
                [fixture.event_key for fixture in fixtures],
                model_version,
                upcoming_model_name,
            )
            results.extend(
                _wrap_upcoming_fixture(fixture, prediction_by_key.get(fixture.event_key))
                for fixture in fixtures
            )
            remaining = limit - len(results)
            if remaining > 0:
                played_rows = list_played_fixtures_with_predictions(
                    db,
                    model_version=model_version,
                    explicit_model_name=played_model_name,
                    from_date=played_from,
                    to_date=played_to,
                    outcome=outcome,
                    limit=remaining,
                    offset=0,
                    player_name=player_name,
                    odds_required=odds_required,
                )
                results.extend(
                    _wrap_played_fixture(fixture, stored_prediction)
                    for fixture, stored_prediction in played_rows
                )
        else:
            played_rows = list_played_fixtures_with_predictions(
                db,
                model_version=model_version,
                explicit_model_name=played_model_name,
                from_date=played_from,
                to_date=played_to,
                outcome=outcome,
                limit=limit,
                offset=offset - upcoming_total,
                player_name=player_name,
                odds_required=odds_required,
            )
            results = [
                _wrap_played_fixture(fixture, stored_prediction)
                for fixture, stored_prediction in played_rows
            ]

    return FixturesWithPredictionsPage(
        items=results,
        total=total,
        offset=offset,
        limit=limit,
    )


def compute_daily_prediction_stats(
    db: Session,
    model_version: ModelVersion,
    model_name: str | None = None,
    from_day: int = 0,
    to_day: int | None = None,
    reference_date: date | None = None,
) -> DailyPredictionStatsResponse:
    today = reference_date or date.today()
    days: list[DailyPredictionStatsDay] = []

    stmt = select(MatchPrediction).where(MatchPrediction.model_version == model_version)
    if model_name is not None:
        stmt = stmt.where(MatchPrediction.model_name == model_name)
    predictions = list(db.scalars(stmt).all())
    event_dates, actual_winners = _prediction_match_context(db, predictions)
    odds_by_key = _prediction_odds_context(db, predictions)

    if to_day is None:
        available_offsets = [
            (today - event_date).days
            for event_date in event_dates.values()
            if event_date is not None and event_date <= today
        ]
        to_day = max(available_offsets, default=from_day)
        to_day = max(to_day, from_day)

    for day_offset in range(from_day, to_day + 1):
        target_date = today - timedelta(days=day_offset)
        day_predictions = [
            prediction
            for prediction in predictions
            if event_dates.get(prediction.event_key) == target_date
        ]
        resolved = [
            prediction
            for prediction in day_predictions
            if _actual_winner(prediction, actual_winners) is not None
        ]
        correct = [
            prediction
            for prediction in resolved
            if _is_correct(prediction, actual_winners)
        ]
        pending = len(day_predictions) - len(resolved)
        lost = len(resolved) - len(correct)
        accuracy_pct = (
            (len(correct) / len(resolved) * 100.0) if resolved else None
        )
        odds_stats = _odds_stats_payload(resolved, actual_winners, odds_by_key)
        days.append(
            DailyPredictionStatsDay(
                day_offset=day_offset,
                date=target_date,
                predictions_total=len(day_predictions),
                predictions_resolved=len(resolved),
                predictions_correct=len(correct),
                predictions_lost=lost,
                accuracy_pct=accuracy_pct,
                pending=pending,
                predictions_with_odds=odds_stats.predictions_with_odds,
                avg_predicted_winner_odds=odds_stats.avg_predicted_winner_odds,
                avg_winning_odds=odds_stats.avg_winning_odds,
                theoretical_profit_units=odds_stats.theoretical_profit_units,
                theoretical_roi_pct=odds_stats.theoretical_roi_pct,
            )
        )

    return DailyPredictionStatsResponse(model_version=model_version, days=days)


def _prediction_match_context(
    db: Session,
    predictions: list[MatchPrediction],
) -> tuple[dict[int, date | None], dict[int, str | None]]:
    event_dates: dict[int, date | None] = {}
    actual_winners: dict[int, str | None] = {}
    for prediction in predictions:
        if prediction.event_key not in event_dates:
            event_dates[prediction.event_key] = _event_date_for_prediction(
                db,
                prediction.event_key,
            )
        if prediction.event_key not in actual_winners:
            actual_winners[prediction.event_key] = prediction.actual_winner or db.scalar(
                select(Fixture.event_winner).where(Fixture.event_key == prediction.event_key)
            )
    return event_dates, actual_winners


def _prediction_odds_context(
    db: Session,
    predictions: list[MatchPrediction],
) -> dict[int, MatchWinnerOddsAverage | None]:
    odds_by_key: dict[int, MatchWinnerOddsAverage | None] = {}
    for prediction in predictions:
        if prediction.event_key in odds_by_key:
            continue

        fixture = db.scalar(
            select(Fixture).where(
                Fixture.event_key == prediction.event_key,
                Fixture.odds.is_not(None),
            )
        )
        if fixture is not None:
            odds_by_key[prediction.event_key] = _fixture_odds(fixture)
            continue

        next_fixture = db.scalar(
            select(NextFixture).where(
                NextFixture.event_key == prediction.event_key,
                NextFixture.odds.is_not(None),
            )
        )
        odds_by_key[prediction.event_key] = (
            _next_fixture_odds(next_fixture) if next_fixture is not None else None
        )
    return odds_by_key


def _actual_winner(
    prediction: MatchPrediction,
    actual_winners: dict[int, str | None],
) -> str | None:
    return prediction.actual_winner or actual_winners.get(prediction.event_key)


def _is_correct(
    prediction: MatchPrediction,
    actual_winners: dict[int, str | None],
) -> bool:
    actual_winner = _actual_winner(prediction, actual_winners)
    if actual_winner is None:
        return False
    return prediction.predicted_winner == actual_winner


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _odds_stats_payload(
    resolved_predictions: list[MatchPrediction],
    actual_winners: dict[int, str | None],
    odds_by_key: dict[int, MatchWinnerOddsAverage | None],
) -> PredictionOddsStats:
    """Unit-stake P/L for resolved singles only (void/cancelled never enter here).

    Callers pass predictions that already have a bettable winner; cancelled /
    non-played matches are excluded so they cannot count as losses.
    """
    predicted_winner_odds: list[float] = []
    winning_odds: list[float] = []
    profits: list[float] = []
    stake_total = 0.0

    for prediction in resolved_predictions:
        odds = _predicted_winner_odds(
            prediction.predicted_winner,
            odds_by_key.get(prediction.event_key),
        )
        if odds is None:
            continue

        actual_winner = _actual_winner(prediction, actual_winners)
        settlement = settle_simulated_bet(
            lifecycle="completed",
            predicted_winner=prediction.predicted_winner,
            actual_winner=actual_winner,
            market_odds=odds,
        )
        if not settlement.include_in_roi:
            continue

        predicted_winner_odds.append(odds)
        if settlement.is_correct:
            winning_odds.append(odds)
        profits.append(settlement.profit_units)
        stake_total += settlement.stake_units

    profit = sum(profits)
    stake_count = len(profits)
    return PredictionOddsStats(
        predictions_with_odds=stake_count,
        avg_predicted_winner_odds=_average(predicted_winner_odds),
        avg_winning_odds=_average(winning_odds),
        theoretical_profit_units=profit,
        theoretical_roi_pct=(profit / stake_total * 100.0) if stake_total else None,
    )


def _summary_payload(
    predictions: list[MatchPrediction],
    actual_winners: dict[int, str | None],
) -> tuple[int, int, int, int, float | None]:
    resolved = [
        prediction
        for prediction in predictions
        if _actual_winner(prediction, actual_winners) is not None
    ]
    correct = [
        prediction
        for prediction in resolved
        if _is_correct(prediction, actual_winners)
    ]
    pending = len(predictions) - len(resolved)
    lost = len(resolved) - len(correct)
    accuracy_pct = (len(correct) / len(resolved) * 100.0) if resolved else None
    return len(resolved), len(correct), lost, pending, accuracy_pct


def _model_breakdown(
    predictions: list[MatchPrediction],
    actual_winners: dict[int, str | None],
    odds_by_key: dict[int, MatchWinnerOddsAverage | None],
) -> list[PredictionModelBreakdown]:
    grouped: dict[tuple[str, str | None], list[MatchPrediction]] = defaultdict(list)
    for prediction in predictions:
        grouped[(prediction.model_version, prediction.model_name)].append(prediction)

    breakdown: list[PredictionModelBreakdown] = []
    for (model_version, model_name), group in sorted(grouped.items()):
        resolved, correct, lost, pending, accuracy_pct = _summary_payload(
            group,
            actual_winners,
        )
        resolved_group = [
            prediction
            for prediction in group
            if _actual_winner(prediction, actual_winners) is not None
        ]
        odds_stats = _odds_stats_payload(resolved_group, actual_winners, odds_by_key)
        breakdown.append(
            PredictionModelBreakdown(
                model_version=model_version,
                model_name=model_name,
                predictions_total=len(group),
                predictions_resolved=resolved,
                predictions_correct=correct,
                predictions_lost=lost,
                accuracy_pct=accuracy_pct,
                pending=pending,
                predictions_with_odds=odds_stats.predictions_with_odds,
                avg_predicted_winner_odds=odds_stats.avg_predicted_winner_odds,
                avg_winning_odds=odds_stats.avg_winning_odds,
                theoretical_profit_units=odds_stats.theoretical_profit_units,
                theoretical_roi_pct=odds_stats.theoretical_roi_pct,
            )
        )
    return breakdown


def compute_prediction_summary(
    db: Session,
    model_version: ModelVersion,
    model_name: str | None = None,
) -> PredictionSummaryResponse:
    stmt = select(MatchPrediction).where(MatchPrediction.model_version == model_version)
    if model_name is not None:
        stmt = stmt.where(MatchPrediction.model_name == model_name)
    predictions = list(db.scalars(stmt).all())
    _event_dates, actual_winners = _prediction_match_context(db, predictions)
    odds_by_key = _prediction_odds_context(db, predictions)
    resolved, correct, lost, pending, accuracy_pct = _summary_payload(
        predictions,
        actual_winners,
    )
    resolved_predictions = [
        prediction
        for prediction in predictions
        if _actual_winner(prediction, actual_winners) is not None
    ]
    odds_stats = _odds_stats_payload(resolved_predictions, actual_winners, odds_by_key)
    return PredictionSummaryResponse(
        model_version=model_version,
        predictions_total=len(predictions),
        predictions_resolved=resolved,
        predictions_correct=correct,
        predictions_lost=lost,
        accuracy_pct=accuracy_pct,
        pending=pending,
        predictions_with_odds=odds_stats.predictions_with_odds,
        avg_predicted_winner_odds=odds_stats.avg_predicted_winner_odds,
        avg_winning_odds=odds_stats.avg_winning_odds,
        theoretical_profit_units=odds_stats.theoretical_profit_units,
        theoretical_roi_pct=odds_stats.theoretical_roi_pct,
        breakdown=_model_breakdown(predictions, actual_winners, odds_by_key),
    )
