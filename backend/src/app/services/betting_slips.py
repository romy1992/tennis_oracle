from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from backend.src.app.ml.datasets.odds_builder import (
    FixtureOddsRecord,
    MatchWinnerOddsAverage,
    average_match_winner_odds_from_record,
    no_vig_market_probabilities,
)
from backend.src.app.ml.model_selection import select_best_model
from backend.src.app.ml.model_versioning import ModelVersion
from backend.src.app.models import (
    BettingSlip,
    BettingSlipDay,
    BettingSlipPick,
    Fixture,
    MatchPrediction,
    NextFixture,
)
from backend.src.app.schemas.betting_slips import (
    BettingSlipCalendarDay,
    BettingSlipCalendarResponse,
    BettingSlipPickRead,
    BettingSlipRead,
    BettingSlipRefreshSummary,
    BettingSlipsDailyResponse,
    BettingSlipsRefreshResponse,
    BettingSlipStatsDay,
    BettingSlipStatsProfile,
    BettingSlipStatsResponse,
    BettingSlipStatsSummary,
)
from backend.src.app.services.predictions import COMPLETED_WINNERS, _predictions_by_event_key, _resolve_model_name

PickStatus = Literal["pending", "won", "lost"]
SlipStatus = Literal["pending", "won", "lost"]

DEFAULT_STAKE = 10.0
DEFAULT_SLIP_COUNT = 5
DEFAULT_PICKS_PER_SLIP = 5

SLIP_PROFILES: tuple[dict[str, str | int], ...] = (
    {
        "slip_key": "safe",
        "label": "Sicura",
        "description": "Alta confidence, quote contenute",
        "target_picks": 5,
    },
    {
        "slip_key": "balanced",
        "label": "Bilanciata",
        "description": "Buon mix confidence + edge",
        "target_picks": 4,
    },
    {
        "slip_key": "value",
        "label": "Value",
        "description": "Edge piu alto, quote piu alte",
        "target_picks": 4,
    },
    {
        "slip_key": "mix",
        "label": "Mix del giorno",
        "description": "Top score complessivo",
        "target_picks": 5,
    },
    {
        "slip_key": "alternative",
        "label": "Alternativa",
        "description": "Selezione diversificata",
        "target_picks": 4,
    },
)


@dataclass(frozen=True)
class CandidatePick:
    event_key: int
    event_date: date | None
    event_time: time | None
    tournament_name: str | None
    surface: str | None
    player_1_name: str | None
    player_2_name: str | None
    predicted_winner: str
    predicted_winner_label: str
    model_prob: float
    market_prob: float | None
    edge: float | None
    odds: float | None
    confidence: float
    pick_score: float


@dataclass(frozen=True)
class GeneratedSlip:
    slip_key: str
    label: str
    description: str | None
    picks: tuple[CandidatePick, ...]
    combined_odds: float


def _confidence(prob_player_1_win: float | None) -> float | None:
    if prob_player_1_win is None:
        return None
    return max(prob_player_1_win, 1.0 - prob_player_1_win)


def _pick_score(model_prob: float, edge: float | None, odds: float | None) -> float:
    edge_term = (edge or 0.0) * 0.5
    odds_term = math.log(max(odds, 1.01)) * 0.2 if odds is not None else 0.0
    return edge_term + (model_prob - 0.5) * 0.3 + odds_term


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


def _fixture_odds(fixture: NextFixture) -> MatchWinnerOddsAverage | None:
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


def _predicted_winner_odds(
    predicted_winner: str | None,
    odds: MatchWinnerOddsAverage | None,
) -> float | None:
    if odds is None or predicted_winner is None:
        return None
    if predicted_winner == "First Player":
        return odds.avg_player_1_odds
    if predicted_winner == "Second Player":
        return odds.avg_player_2_odds
    return None


def _market_prob_for_winner(
    predicted_winner: str,
    odds: MatchWinnerOddsAverage,
) -> float | None:
    try:
        market_prob_1, market_prob_2 = no_vig_market_probabilities(
            odds.avg_player_1_odds,
            odds.avg_player_2_odds,
        )
    except ValueError:
        return None
    if predicted_winner == "First Player":
        return market_prob_1
    if predicted_winner == "Second Player":
        return market_prob_2
    return None


def _model_prob_for_winner(
    predicted_winner: str,
    prob_player_1_win: float | None,
) -> float | None:
    if prob_player_1_win is None:
        return None
    if predicted_winner == "First Player":
        return prob_player_1_win
    if predicted_winner == "Second Player":
        return 1.0 - prob_player_1_win
    return None


def build_candidate_pool(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
) -> list[CandidatePick]:
    fixtures = list(
        db.scalars(
            select(NextFixture)
            .where(
                NextFixture.is_completed.is_(False),
                NextFixture.event_date == slip_date,
            )
            .order_by(
                NextFixture.event_time.asc().nullslast(),
                NextFixture.event_key.asc(),
            )
        ).all()
    )
    if not fixtures:
        return []

    prediction_by_key = _predictions_by_event_key(
        db,
        [fixture.event_key for fixture in fixtures],
        model_version,
        model_name,
    )

    candidates: list[CandidatePick] = []
    for fixture in fixtures:
        prediction = prediction_by_key.get(fixture.event_key)
        if prediction is None or prediction.predicted_winner not in COMPLETED_WINNERS:
            continue

        odds = _fixture_odds(fixture)
        winner_odds = _predicted_winner_odds(prediction.predicted_winner, odds)
        model_prob = _model_prob_for_winner(prediction.predicted_winner, prediction.prob_player_1_win)
        market_prob = (
            _market_prob_for_winner(prediction.predicted_winner, odds)
            if odds is not None
            else None
        )
        confidence = _confidence(prediction.prob_player_1_win)
        if model_prob is None or confidence is None:
            continue

        edge = model_prob - market_prob if market_prob is not None else None

        candidates.append(
            CandidatePick(
                event_key=fixture.event_key,
                event_date=fixture.event_date,
                event_time=fixture.event_time,
                tournament_name=fixture.tournament_name,
                surface=fixture.surface,
                player_1_name=fixture.event_first_player,
                player_2_name=fixture.event_second_player,
                predicted_winner=prediction.predicted_winner,
                predicted_winner_label=_winner_label(
                    prediction.predicted_winner,
                    fixture.event_first_player,
                    fixture.event_second_player,
                ),
                model_prob=model_prob,
                market_prob=market_prob,
                edge=edge,
                odds=winner_odds,
                confidence=confidence,
                pick_score=_pick_score(model_prob, edge, winner_odds),
            )
        )

    candidates.sort(key=lambda candidate: candidate.pick_score, reverse=True)
    return candidates


def _diversity_bonus(candidate: CandidatePick, selected: list[CandidatePick]) -> float:
    bonus = 0.0
    used_tournaments = {pick.tournament_name for pick in selected if pick.tournament_name}
    used_surfaces = {pick.surface for pick in selected if pick.surface}
    if candidate.tournament_name and candidate.tournament_name not in used_tournaments:
        bonus += 0.05
    if candidate.surface and candidate.surface not in used_surfaces:
        bonus += 0.03
    return bonus


def _select_picks_simple(
    pool: list[CandidatePick],
    *,
    count: int,
    exclude_keys: set[int],
    sort_key,
    extra_filter=None,
) -> list[CandidatePick]:
    filtered = [
        candidate
        for candidate in pool
        if candidate.event_key not in exclude_keys
        and (extra_filter(candidate) if extra_filter is not None else True)
    ]
    filtered.sort(key=lambda candidate: sort_key(candidate) + _diversity_bonus(candidate, []), reverse=True)

    selected_picks: list[CandidatePick] = []
    remaining = filtered.copy()
    while len(selected_picks) < count and remaining:
        remaining.sort(
            key=lambda candidate: sort_key(candidate) + _diversity_bonus(candidate, selected_picks),
            reverse=True,
        )
        next_pick = remaining.pop(0)
        if next_pick.event_key in {pick.event_key for pick in selected_picks}:
            continue
        selected_picks.append(next_pick)
    return selected_picks


def _combined_odds(picks: list[CandidatePick]) -> float:
    total = 1.0
    for pick in picks:
        if pick.odds is not None:
            total *= pick.odds
    return round(total, 4)


def generate_slips(
    candidates: list[CandidatePick],
    *,
    slip_count: int = DEFAULT_SLIP_COUNT,
    picks_per_slip: int = DEFAULT_PICKS_PER_SLIP,
) -> tuple[list[GeneratedSlip], list[str]]:
    warnings: list[str] = []
    if not candidates:
        return [], ["Nessun candidato disponibile per generare schedine."]

    profiles = list(SLIP_PROFILES[:slip_count])
    generated: list[GeneratedSlip] = []
    used_keys: set[int] = set()

    for profile in profiles:
        target = min(int(profile["target_picks"]), picks_per_slip)
        slip_key = str(profile["slip_key"])

        if slip_key == "safe":
            pool_filter = None
            sort_key = lambda candidate: candidate.confidence
        elif slip_key == "balanced":
            pool_filter = None
            sort_key = lambda candidate: candidate.pick_score
        elif slip_key == "value":
            pool_filter = None
            sort_key = lambda candidate: candidate.edge or 0.0
        elif slip_key == "mix":
            pool_filter = None
            sort_key = lambda candidate: candidate.pick_score
        else:
            pool_filter = None
            sort_key = lambda candidate: candidate.pick_score

        exclude = used_keys if slip_key == "alternative" else set()
        picks = _select_picks_simple(
            candidates,
            count=target,
            exclude_keys=exclude,
            sort_key=sort_key,
            extra_filter=pool_filter,
        )
        if len(picks) < 4:
            warnings.append(
                f"Schedina '{profile['label']}': solo {len(picks)} pick disponibili."
            )
            if not picks:
                continue

        used_keys.update(pick.event_key for pick in picks)
        generated.append(
            GeneratedSlip(
                slip_key=slip_key,
                label=str(profile["label"]),
                description=str(profile["description"]),
                picks=tuple(picks),
                combined_odds=_combined_odds(picks),
            )
        )

    if len(generated) < slip_count:
        warnings.append(
            f"Solo {len(generated)} schedine generate: candidati insufficienti."
        )

    return generated, warnings


def _slips_exist(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
) -> bool:
    count = db.scalar(
        select(func.count())
        .select_from(BettingSlip)
        .where(
            BettingSlip.slip_date == slip_date,
            BettingSlip.model_version == model_version,
            BettingSlip.model_name == model_name,
        )
    )
    return int(count or 0) > 0


def _delete_slips_for_date(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
) -> None:
    db.execute(
        delete(BettingSlip).where(
            BettingSlip.slip_date == slip_date,
            BettingSlip.model_version == model_version,
            BettingSlip.model_name == model_name,
        )
    )
    db.commit()


def _count_upcoming_fixtures_on_date(db: Session, slip_date: date) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(NextFixture)
            .where(
                NextFixture.is_completed.is_(False),
                NextFixture.event_date == slip_date,
            )
        )
        or 0
    )


def _upcoming_window_end(db: Session, today: date) -> date:
    max_date = db.scalar(
        select(func.max(NextFixture.event_date)).where(
            NextFixture.is_completed.is_(False),
            NextFixture.event_date >= today,
        )
    )
    return max_date or today


def _upsert_slip_day(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
    candidate_pool_size: int,
    slip_count: int,
) -> None:
    now = datetime.now()
    fixture_count = _count_upcoming_fixtures_on_date(db, slip_date)
    row = db.scalar(
        select(BettingSlipDay).where(
            BettingSlipDay.slip_date == slip_date,
            BettingSlipDay.model_version == model_version,
            BettingSlipDay.model_name == model_name,
        )
    )
    if row is None:
        db.add(
            BettingSlipDay(
                slip_date=slip_date,
                model_version=model_version,
                model_name=model_name,
                candidate_pool_size=candidate_pool_size,
                slip_count=slip_count,
                fixture_count=fixture_count,
                generated_at=now,
                updated_at=now,
            )
        )
    else:
        row.candidate_pool_size = candidate_pool_size
        row.slip_count = slip_count
        row.fixture_count = fixture_count
        row.updated_at = now
    db.commit()


def _slip_counts_by_date(
    db: Session,
    *,
    model_version: ModelVersion,
    model_name: str,
) -> dict[date, int]:
    rows = db.execute(
        select(BettingSlip.slip_date, func.count())
        .where(
            BettingSlip.model_version == model_version,
            BettingSlip.model_name == model_name,
        )
        .group_by(BettingSlip.slip_date)
    ).all()
    return {slip_date: int(count) for slip_date, count in rows}


def get_betting_slip_calendar(
    db: Session,
    *,
    model_version: ModelVersion = "v2",
    model_name: str | None = None,
) -> BettingSlipCalendarResponse:
    today = date.today()
    resolved_model_name = model_name or _resolve_model_name(model_version, None)
    if resolved_model_name is None:
        resolved_model_name = select_best_model(model_version).model_name

    window_end = _upcoming_window_end(db, today)
    slip_counts = _slip_counts_by_date(
        db,
        model_version=model_version,
        model_name=resolved_model_name,
    )

    historical_dates = {
        slip_date
        for slip_date, count in slip_counts.items()
        if slip_date < today and count > 0
    }
    registry_rows = {
        row.slip_date: row
        for row in db.scalars(
            select(BettingSlipDay).where(
                BettingSlipDay.model_version == model_version,
                BettingSlipDay.model_name == resolved_model_name,
            )
        ).all()
    }
    historical_dates.update(
        slip_date for slip_date in registry_rows if slip_date < today
    )

    forward_dates = [
        today + timedelta(days=offset)
        for offset in range((window_end - today).days + 1)
    ]
    all_dates = sorted(historical_dates | set(forward_dates))

    calendar_days: list[BettingSlipCalendarDay] = []
    for slip_date in all_dates:
        registry = registry_rows.get(slip_date)
        slip_count = slip_counts.get(slip_date, registry.slip_count if registry else 0)
        fixture_count = (
            _count_upcoming_fixtures_on_date(db, slip_date)
            if slip_date >= today
            else (registry.fixture_count if registry else 0)
        )
        calendar_days.append(
            BettingSlipCalendarDay(
                date=slip_date,
                is_today=slip_date == today,
                is_past=slip_date < today,
                is_upcoming=slip_date > today,
                has_slips=slip_count > 0,
                slip_count=slip_count,
                fixture_count=fixture_count,
                candidate_pool_size=(
                    registry.candidate_pool_size if registry is not None else None
                ),
            )
        )

    history_from = min(historical_dates) if historical_dates else None
    return BettingSlipCalendarResponse(
        today=today,
        window_from=today,
        window_to=window_end,
        history_from=history_from,
        model_version=model_version,
        model_name=resolved_model_name,
        days=calendar_days,
    )


def _persist_slips(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
    generated_slips: list[GeneratedSlip],
) -> None:
    generated_at = datetime.now()
    for slip_data in generated_slips:
        slip = BettingSlip(
            slip_date=slip_date,
            slip_key=slip_data.slip_key,
            label=slip_data.label,
            description=slip_data.description,
            model_version=model_version,
            model_name=model_name,
            pick_count=len(slip_data.picks),
            combined_odds=slip_data.combined_odds,
            generated_at=generated_at,
        )
        db.add(slip)
        db.flush()
        for index, pick in enumerate(slip_data.picks):
            db.add(
                BettingSlipPick(
                    betting_slip_id=slip.id,
                    event_key=pick.event_key,
                    event_date=pick.event_date,
                    event_time=pick.event_time,
                    tournament_name=pick.tournament_name,
                    surface=pick.surface,
                    player_1_name=pick.player_1_name,
                    player_2_name=pick.player_2_name,
                    predicted_winner=pick.predicted_winner,
                    predicted_winner_label=pick.predicted_winner_label,
                    model_prob=pick.model_prob,
                    market_prob=pick.market_prob,
                    edge=pick.edge,
                    odds=pick.odds,
                    confidence=pick.confidence,
                    pick_score=pick.pick_score,
                    sort_order=index,
                )
            )
    db.commit()


def _load_slips(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
) -> list[BettingSlip]:
    return list(
        db.scalars(
            select(BettingSlip)
            .options(selectinload(BettingSlip.picks))
            .where(
                BettingSlip.slip_date == slip_date,
                BettingSlip.model_version == model_version,
                BettingSlip.model_name == model_name,
            )
            .order_by(BettingSlip.id.asc())
        ).all()
    )


def _load_outcome_context(
    db: Session,
    event_keys: list[int],
    model_version: ModelVersion,
    model_name: str,
) -> tuple[dict[int, MatchPrediction], dict[int, Fixture]]:
    if not event_keys:
        return {}, {}

    predictions = {
        prediction.event_key: prediction
        for prediction in db.scalars(
            select(MatchPrediction).where(
                MatchPrediction.event_key.in_(event_keys),
                MatchPrediction.model_version == model_version,
                MatchPrediction.model_name == model_name,
            )
        ).all()
    }
    fixtures = {
        fixture.event_key: fixture
        for fixture in db.scalars(
            select(Fixture).where(Fixture.event_key.in_(event_keys))
        ).all()
    }
    return predictions, fixtures


def _resolve_actual_winner(
    pick: BettingSlipPick,
    predictions: dict[int, MatchPrediction],
    fixtures: dict[int, Fixture],
) -> str | None:
    prediction = predictions.get(pick.event_key)
    if prediction is not None and prediction.actual_winner in COMPLETED_WINNERS:
        return prediction.actual_winner

    fixture = fixtures.get(pick.event_key)
    if fixture is not None and fixture.event_winner in COMPLETED_WINNERS:
        return fixture.event_winner

    return None


def _actual_winner_label(
    actual_winner: str | None,
    pick: BettingSlipPick,
) -> str | None:
    if actual_winner is None:
        return None
    return _winner_label(actual_winner, pick.player_1_name, pick.player_2_name)


def _resolve_pick_status(
    pick: BettingSlipPick,
    actual_winner: str | None,
) -> tuple[PickStatus, bool | None]:
    if actual_winner is None:
        return "pending", None
    is_correct = pick.predicted_winner == actual_winner
    return ("won" if is_correct else "lost"), is_correct


def _resolve_slip_status(pick_statuses: list[PickStatus]) -> SlipStatus:
    if any(status == "lost" for status in pick_statuses):
        return "lost"
    if pick_statuses and all(status == "won" for status in pick_statuses):
        return "won"
    return "pending"


def _pick_read(
    pick: BettingSlipPick,
    *,
    predictions: dict[int, MatchPrediction],
    fixtures: dict[int, Fixture],
) -> BettingSlipPickRead:
    actual_winner = _resolve_actual_winner(pick, predictions, fixtures)
    pick_status, is_correct = _resolve_pick_status(pick, actual_winner)
    return BettingSlipPickRead(
        event_key=pick.event_key,
        event_date=pick.event_date,
        event_time=pick.event_time,
        tournament_name=pick.tournament_name,
        surface=pick.surface,
        player_1=pick.player_1_name,
        player_2=pick.player_2_name,
        predicted_winner=pick.predicted_winner,
        predicted_winner_label=pick.predicted_winner_label,
        model_prob=pick.model_prob,
        market_prob=pick.market_prob,
        edge=pick.edge,
        odds=pick.odds,
        confidence=pick.confidence,
        pick_score=pick.pick_score,
        pick_status=pick_status,
        actual_winner_label=_actual_winner_label(actual_winner, pick),
        is_correct=is_correct,
    )


def _slip_read(
    slip: BettingSlip,
    *,
    predictions: dict[int, MatchPrediction],
    fixtures: dict[int, Fixture],
    stake: float,
) -> BettingSlipRead:
    pick_reads = [
        _pick_read(pick, predictions=predictions, fixtures=fixtures)
        for pick in sorted(slip.picks, key=lambda item: item.sort_order)
    ]
    pick_statuses = [pick.pick_status for pick in pick_reads]
    slip_status = _resolve_slip_status(pick_statuses)
    picks_won = sum(1 for status in pick_statuses if status == "won")
    picks_lost = sum(1 for status in pick_statuses if status == "lost")
    picks_pending = sum(1 for status in pick_statuses if status == "pending")
    combined_probability_estimate = 1.0
    for pick in pick_reads:
        if pick.model_prob is not None:
            combined_probability_estimate *= pick.model_prob
    combined_probability_estimate = round(combined_probability_estimate, 6)
    potential_return = round(stake * slip.combined_odds, 2)
    potential_profit = round(potential_return - stake, 2)
    resolved_combined_odds = 1.0
    for pick in pick_reads:
        if pick.pick_status == "won" and pick.odds is not None:
            resolved_combined_odds *= pick.odds
    resolved_combined_odds = round(resolved_combined_odds, 4) if picks_won else None
    theoretical_profit_if_won = potential_profit if slip_status == "won" else None

    return BettingSlipRead(
        id=slip.slip_key,
        slip_key=slip.slip_key,
        label=slip.label,
        description=slip.description,
        picks=pick_reads,
        pick_count=slip.pick_count,
        combined_odds=slip.combined_odds,
        combined_probability_estimate=combined_probability_estimate,
        potential_return=potential_return,
        potential_profit=potential_profit,
        slip_status=slip_status,
        picks_won=picks_won,
        picks_lost=picks_lost,
        picks_pending=picks_pending,
        picks_total=len(pick_reads),
        resolved_combined_odds=resolved_combined_odds,
        theoretical_profit_if_won=theoretical_profit_if_won,
        generated_at=slip.generated_at,
    )


def _build_daily_response(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
    stake: float,
    candidate_pool_size: int,
    warnings: list[str],
) -> BettingSlipsDailyResponse:
    slips = _load_slips(
        db,
        slip_date=slip_date,
        model_version=model_version,
        model_name=model_name,
    )
    event_keys = [pick.event_key for slip in slips for pick in slip.picks]
    predictions, fixtures = _load_outcome_context(db, event_keys, model_version, model_name)
    slip_reads = [
        _slip_read(
            slip,
            predictions=predictions,
            fixtures=fixtures,
            stake=stake,
        )
        for slip in slips
    ]
    return BettingSlipsDailyResponse(
        date=slip_date,
        model_version=model_version,
        model_name=model_name,
        stake=stake,
        candidate_pool_size=candidate_pool_size,
        slips=slip_reads,
        warnings=warnings,
    )


def get_daily_betting_slips(
    db: Session,
    *,
    slip_date: date | None = None,
    model_version: ModelVersion = "v2",
    model_name: str | None = None,
    stake: float = DEFAULT_STAKE,
    slip_count: int = DEFAULT_SLIP_COUNT,
    picks_per_slip: int = DEFAULT_PICKS_PER_SLIP,
    regenerate: bool = False,
) -> BettingSlipsDailyResponse:
    target_date = slip_date or date.today()
    resolved_model_name = model_name or _resolve_model_name(model_version, None)
    if resolved_model_name is None:
        resolved_model_name = select_best_model(model_version).model_name

    warnings: list[str] = []
    candidate_pool_size = 0

    if regenerate and _slips_exist(
        db,
        slip_date=target_date,
        model_version=model_version,
        model_name=resolved_model_name,
    ):
        _delete_slips_for_date(
            db,
            slip_date=target_date,
            model_version=model_version,
            model_name=resolved_model_name,
        )

    if not _slips_exist(
        db,
        slip_date=target_date,
        model_version=model_version,
        model_name=resolved_model_name,
    ):
        candidates = build_candidate_pool(
            db,
            slip_date=target_date,
            model_version=model_version,
            model_name=resolved_model_name,
        )
        candidate_pool_size = len(candidates)
        generated, generation_warnings = generate_slips(
            candidates,
            slip_count=slip_count,
            picks_per_slip=picks_per_slip,
        )
        warnings.extend(generation_warnings)
        if generated:
            _persist_slips(
                db,
                slip_date=target_date,
                model_version=model_version,
                model_name=resolved_model_name,
                generated_slips=generated,
            )
    else:
        candidates = build_candidate_pool(
            db,
            slip_date=target_date,
            model_version=model_version,
            model_name=resolved_model_name,
        )
        candidate_pool_size = len(candidates)

    slip_count = len(
        _load_slips(
            db,
            slip_date=target_date,
            model_version=model_version,
            model_name=resolved_model_name,
        )
    )
    _upsert_slip_day(
        db,
        slip_date=target_date,
        model_version=model_version,
        model_name=resolved_model_name,
        candidate_pool_size=candidate_pool_size,
        slip_count=slip_count,
    )

    return _build_daily_response(
        db,
        slip_date=target_date,
        model_version=model_version,
        model_name=resolved_model_name,
        stake=stake,
        candidate_pool_size=candidate_pool_size,
        warnings=warnings,
    )


def refresh_betting_slips(
    db: Session,
    *,
    slip_date: date | None = None,
    model_version: ModelVersion = "v2",
    model_name: str | None = None,
    stake: float = DEFAULT_STAKE,
    days_back: int = 1,
) -> BettingSlipsRefreshResponse:
    from backend.src.app.services.imports import import_played_fixtures, refresh_matches

    target_date = slip_date or date.today()
    resolved_model_name = model_name or _resolve_model_name(model_version, None)
    if resolved_model_name is None:
        resolved_model_name = select_best_model(model_version).model_name

    import_summary = import_played_fixtures(db, days_back=days_back)
    refresh_summary = refresh_matches(
        db,
        days_forward=10,
        days_back_next=3,
        model_version=model_version,
        model_name=resolved_model_name,
        force_next_import=False,
    )

    daily = get_daily_betting_slips(
        db,
        slip_date=target_date,
        model_version=model_version,
        model_name=resolved_model_name,
        stake=stake,
        regenerate=False,
    )

    predictions_resolved = sum(
        1
        for slip in daily.slips
        for pick in slip.picks
        if pick.pick_status in {"won", "lost"}
    )

    return BettingSlipsRefreshResponse(
        **daily.model_dump(),
        refresh_summary=BettingSlipRefreshSummary(
            fixtures_imported=True,
            predictions_resolved=predictions_resolved,
            slips_updated=len(daily.slips),
            import_status=import_summary.get("import_status"),
            next_fixtures_imported=refresh_summary.get("next_fixtures_imported", False),
        ),
    )


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 1)


def _slip_profit_units(slip: BettingSlipRead, stake: float) -> float:
    if slip.slip_status == "won":
        return stake * slip.combined_odds - stake
    if slip.slip_status == "lost":
        return -stake
    return 0.0


def compute_betting_slip_stats(
    db: Session,
    *,
    model_version: ModelVersion = "v2",
    from_date: date | None = None,
    to_date: date | None = None,
    stake: float = DEFAULT_STAKE,
    all_time: bool = False,
) -> BettingSlipStatsResponse:
    today = date.today()
    if all_time:
        resolved_from = db.scalar(
            select(func.min(BettingSlip.slip_date)).where(
                BettingSlip.model_version == model_version,
            )
        )
        resolved_to = today
        if resolved_from is None:
            resolved_from = today
    else:
        resolved_to = to_date or today
        resolved_from = from_date or (today - timedelta(days=30))

    slips = list(
        db.scalars(
            select(BettingSlip)
            .options(selectinload(BettingSlip.picks))
            .where(
                BettingSlip.model_version == model_version,
                BettingSlip.slip_date >= resolved_from,
                BettingSlip.slip_date <= resolved_to,
            )
            .order_by(BettingSlip.slip_date.asc(), BettingSlip.id.asc())
        ).all()
    )

    event_keys = [pick.event_key for slip in slips for pick in slip.picks]
    model_names = {slip.model_name for slip in slips}
    predictions: dict[int, MatchPrediction] = {}
    fixtures: dict[int, Fixture] = {}
    for model_name in model_names or {select_best_model(model_version).model_name}:
        model_predictions, model_fixtures = _load_outcome_context(
            db,
            event_keys,
            model_version,
            model_name,
        )
        predictions.update(model_predictions)
        fixtures.update(model_fixtures)

    slips_by_date: dict[date, list[BettingSlipRead]] = defaultdict(list)
    profile_stats: dict[str, dict[str, int | str]] = defaultdict(
        lambda: {"slips_won": 0, "slips_lost": 0, "slips_pending": 0, "slips_total": 0}
    )

    summary_slips_won = 0
    summary_slips_lost = 0
    summary_slips_pending = 0
    summary_picks_won = 0
    summary_picks_lost = 0
    summary_picks_pending = 0
    summary_picks_total = 0

    for slip in slips:
        slip_read = _slip_read(
            slip,
            predictions=predictions,
            fixtures=fixtures,
            stake=stake,
        )
        slips_by_date[slip.slip_date].append(slip_read)

        profile = profile_stats[slip.slip_key]
        profile["label"] = slip.label
        profile["slips_total"] = int(profile["slips_total"]) + 1
        if slip_read.slip_status == "won":
            profile["slips_won"] = int(profile["slips_won"]) + 1
            summary_slips_won += 1
        elif slip_read.slip_status == "lost":
            profile["slips_lost"] = int(profile["slips_lost"]) + 1
            summary_slips_lost += 1
        else:
            profile["slips_pending"] = int(profile["slips_pending"]) + 1
            summary_slips_pending += 1

        summary_picks_won += slip_read.picks_won
        summary_picks_lost += slip_read.picks_lost
        summary_picks_pending += slip_read.picks_pending
        summary_picks_total += slip_read.picks_total

    days: list[BettingSlipStatsDay] = []
    current = resolved_from
    while current <= resolved_to:
        day_slips = slips_by_date.get(current, [])
        day_slips_won = sum(1 for slip in day_slips if slip.slip_status == "won")
        day_slips_lost = sum(1 for slip in day_slips if slip.slip_status == "lost")
        day_slips_pending = sum(1 for slip in day_slips if slip.slip_status == "pending")
        day_picks_won = sum(slip.picks_won for slip in day_slips)
        day_picks_lost = sum(slip.picks_lost for slip in day_slips)
        day_picks_pending = sum(slip.picks_pending for slip in day_slips)
        day_picks_total = sum(slip.picks_total for slip in day_slips)
        day_profits = [
            _slip_profit_units(slip, stake)
            for slip in day_slips
            if slip.slip_status in {"won", "lost"}
        ]
        day_profit_units = round(sum(day_profits), 2)
        day_stake = stake * len(day_profits)
        days.append(
            BettingSlipStatsDay(
                date=current,
                slips_total=len(day_slips),
                slips_won=day_slips_won,
                slips_lost=day_slips_lost,
                slips_pending=day_slips_pending,
                picks_total=day_picks_total,
                picks_won=day_picks_won,
                picks_lost=day_picks_lost,
                picks_pending=day_picks_pending,
                slip_win_rate_pct=_pct(day_slips_won, day_slips_won + day_slips_lost),
                pick_hit_rate_pct=_pct(day_picks_won, day_picks_won + day_picks_lost),
                theoretical_profit_units=day_profit_units,
                theoretical_roi_pct=round((day_profit_units / day_stake) * 100, 1)
                if day_stake
                else None,
            )
        )
        current += timedelta(days=1)

    total_resolved_slips = summary_slips_won + summary_slips_lost
    total_resolved_picks = summary_picks_won + summary_picks_lost
    total_profit_units = round(
        sum(_slip_profit_units(slip, stake) for slips in slips_by_date.values() for slip in slips if slip.slip_status in {"won", "lost"}),
        2,
    )
    total_stake = stake * len(
        [
            slip
            for slips in slips_by_date.values()
            for slip in slips
            if slip.slip_status in {"won", "lost"}
        ]
    )

    by_profile = [
        BettingSlipStatsProfile(
            slip_key=slip_key,
            label=str(stats["label"]),
            slips_won=int(stats["slips_won"]),
            slips_lost=int(stats["slips_lost"]),
            slips_pending=int(stats["slips_pending"]),
            slips_total=int(stats["slips_total"]),
            slip_win_rate_pct=_pct(
                int(stats["slips_won"]),
                int(stats["slips_won"]) + int(stats["slips_lost"]),
            ),
        )
        for slip_key, stats in sorted(profile_stats.items())
    ]

    return BettingSlipStatsResponse(
        model_version=model_version,
        from_date=resolved_from,
        to_date=resolved_to,
        days=days,
        summary=BettingSlipStatsSummary(
            slips_total=len(slips),
            slips_won=summary_slips_won,
            slips_lost=summary_slips_lost,
            slips_pending=summary_slips_pending,
            picks_total=summary_picks_total,
            picks_won=summary_picks_won,
            picks_lost=summary_picks_lost,
            picks_pending=summary_picks_pending,
            slip_win_rate_pct=_pct(summary_slips_won, total_resolved_slips),
            pick_hit_rate_pct=_pct(summary_picks_won, total_resolved_picks),
            theoretical_profit_units=total_profit_units,
            theoretical_roi_pct=round((total_profit_units / total_stake) * 100, 1)
            if total_stake
            else None,
            by_profile=by_profile,
        ),
    )
