from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.ml.datasets.odds_builder import (
    FixtureOddsRecord,
    MatchWinnerOddsAverage,
    average_match_winner_odds_from_record,
    has_real_odds,
    no_vig_market_probabilities,
)
from backend.src.app.ml.datasets.first_set_winner_odds_builder import (
    average_first_set_winner_odds_from_record,
)
from backend.src.app.ml.datasets.over_under_games_odds_builder import (
    DEFAULT_LINE as OU_DEFAULT_LINE,
    average_over_under_games_odds_from_record,
)
from backend.src.app.ml.datasets.score_parser import parse_fixture_score, target_over_line
from backend.src.app.ml.model_versioning import (
    DEFAULT_ACTIVE_MATCH_WINNER_VERSION,
    MODEL_VERSIONS,
    ModelVersion,
)
from backend.src.app.ml.prediction.extra_markets_predictor import (
    FIRST_SET_WINNER_MODEL_NAME,
    FIRST_SET_WINNER_MODEL_VERSION,
    OVER_UNDER_GAMES_MODEL_NAME,
    OVER_UNDER_GAMES_MODEL_VERSION,
)
from backend.src.app.ml.prediction.predictor import DEFAULT_MODEL_NAME
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
    BettingSlipMarketStatsRow,
    BettingSlipMarketModelRead,
    BettingSlipModelStatsResponse,
    BettingSlipModelStatsRow,
    BettingSlipPickRead,
    BettingSlipRead,
    BettingSlipRefreshSummary,
    BettingSlipsDailyResponse,
    BettingSlipsRefreshResponse,
    BettingSlipStatsDay,
    BettingSlipStatsKind,
    BettingSlipStatsProfile,
    BettingSlipStatsResponse,
    BettingSlipStatsStrategy,
    BettingSlipStatsSummary,
    SlipKind,
    StrategyFamily,
)
from backend.src.app.services.match_lifecycle import (
    MatchLifecycleStatus,
    classify_match_lifecycle,
    is_eligible_for_slip_pool,
    match_lifecycle_label,
    resolve_slip_status_from_picks,
    settle_simulated_bet,
    slip_profit_units,
)
from backend.src.app.services.predictions import COMPLETED_WINNERS, _predictions_by_event_key, _resolve_model_name
from backend.src.app.services.published_predictions import list_latest_published_predictions_by_event_keys
from backend.src.app.services.single_match_value import (
    DEFAULT_MIN_EDGE_PERCENT,
    calculate_expected_roi,
    calculate_void_odds,
    classify_single_bet_value,
)

PickStatus = Literal["pending", "won", "lost", "void"]
SlipStatus = Literal["pending", "won", "lost", "void"]
ValueDecision = Literal["PLAY", "BORDERLINE", "NO BET"]

DEFAULT_STAKE = 10.0
DEFAULT_PICKS_PER_SLIP = 5


def _parse_clock_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid betting slip clock time: {value!r}") from exc
    return parsed.replace(second=0, microsecond=0)


def _utc_now_naive(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current
    return current.astimezone(timezone.utc).replace(tzinfo=None)


def _local_now(settings: Settings, value: datetime | None = None) -> datetime:
    tz = ZoneInfo(settings.betting_slip_timezone)
    if value is None:
        return datetime.now(tz)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _pool_close_utc_naive(
    slip_date: date,
    *,
    settings: Settings,
) -> datetime:
    tz = ZoneInfo(settings.betting_slip_timezone)
    local_close = datetime.combine(
        slip_date,
        _parse_clock_time(settings.betting_slip_pool_close_time),
        tzinfo=tz,
    )
    return local_close.astimezone(timezone.utc).replace(tzinfo=None)

# Mercati inclusi di default nel pool "a valore" delle schedine. Tutti e tre
# hanno quote bookmaker reali (Home/Away, Home/Away 1st Set, O/U games).
DEFAULT_SLIP_MARKETS: tuple[str, ...] = (
    "match_winner",
    "first_set_winner",
    "over_under_games",
)

STRONG_MARKETS_V1: tuple[str, ...] = ("first_set_winner",)
STRATEGY_EXPERIMENT_MODEL_VERSION = "v4"
STRATEGY_EXPERIMENT_MODEL_NAME = "voting_ensemble"

STRATEGY_FAMILY_LABELS: dict[str, str] = {
    "generic": "Generiche",
    "play_only": "Solo PLAY",
    "strong_markets": "Mercati forti",
    "selective": "Selettive",
}


def _slip_market_models(
    match_winner_model_version: ModelVersion,
    match_winner_model_name: str,
) -> list[BettingSlipMarketModelRead]:
    """Describe the three independent production models feeding the pool."""

    return [
        BettingSlipMarketModelRead(
            market="match_winner",
            label="Match Winner",
            model_version=match_winner_model_version,
            model_name=match_winner_model_name,
        ),
        BettingSlipMarketModelRead(
            market="first_set_winner",
            label="Primo set",
            model_version=FIRST_SET_WINNER_MODEL_VERSION,
            model_name=FIRST_SET_WINNER_MODEL_NAME,
        ),
        BettingSlipMarketModelRead(
            market="over_under_games",
            label="Over/Under",
            model_version=OVER_UNDER_GAMES_MODEL_VERSION,
            model_name=OVER_UNDER_GAMES_MODEL_NAME,
        ),
    ]


SLIP_PROFILES: tuple[dict[str, object], ...] = (
    {
        "slip_key": "play_double_score",
        "label": "Play · Doppia",
        "description": "Solo PLAY: 2 pick ordinati per score (edge+confidence+quota)",
        "target_picks": 2,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "score",
    },
    {
        "slip_key": "play_safe",
        "label": "Play · Sicura",
        "description": "Solo PLAY: alta confidence, quote contenute",
        "target_picks": 5,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "confidence",
    },
    {
        "slip_key": "play_balanced",
        "label": "Play · Bilanciata",
        "description": "Solo PLAY: mix confidence + edge",
        "target_picks": 4,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "score",
    },
    {
        "slip_key": "play_value",
        "label": "Play · Value",
        "description": "Solo PLAY: edge e quote piu alti",
        "target_picks": 4,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "edge",
    },
    {
        "slip_key": "soft_safe",
        "label": "Play+Border · Sicura",
        "description": "PLAY e BORDERLINE: selezione prudente",
        "target_picks": 5,
        "allowed_decisions": ("PLAY", "BORDERLINE"),
        "sort_mode": "confidence",
    },
    {
        "slip_key": "soft_balanced",
        "label": "Play+Border · Bilanciata",
        "description": "PLAY e BORDERLINE: mix del giorno",
        "target_picks": 4,
        "allowed_decisions": ("PLAY", "BORDERLINE"),
        "sort_mode": "score",
    },
    {
        "slip_key": "soft_value",
        "label": "Play+Border · Value",
        "description": "PLAY e BORDERLINE: punta sull'edge",
        "target_picks": 4,
        "allowed_decisions": ("PLAY", "BORDERLINE"),
        "sort_mode": "edge",
    },
    {
        "slip_key": "mixed_safe",
        "label": "Mista · Sicura",
        "description": "Tutti gli stati: selezione piu diversificata",
        "target_picks": 5,
        "allowed_decisions": ("PLAY", "BORDERLINE", "NO BET"),
        "sort_mode": "confidence",
    },
    {
        "slip_key": "mixed_balanced",
        "label": "Mista · Bilanciata",
        "description": "Tutti gli stati: mix completo del giorno",
        "target_picks": 4,
        "allowed_decisions": ("PLAY", "BORDERLINE", "NO BET"),
        "sort_mode": "score",
    },
    {
        "slip_key": "mixed_value",
        "label": "Mista · Value",
        "description": "Tutti gli stati: massima aggressivita sull'edge",
        "target_picks": 4,
        "allowed_decisions": ("PLAY", "BORDERLINE", "NO BET"),
        "sort_mode": "edge",
    },
)

DEFAULT_SLIP_COUNT = len(SLIP_PROFILES)
MAX_SLIP_COUNT = len(SLIP_PROFILES)

# Progressive ladders (scalate): single-leg steps ordered by kickoff; each win's
# return is reinvested in the next step. Stored as BettingSlip with slip_key
# prefix ``ladder_`` (no schema migration). P/L vs base stake matches an
# accumulator of the non-void legs.
LADDER_PROFILES: tuple[dict[str, object], ...] = (
    {
        "slip_key": "ladder_play_3",
        "label": "Scalata · Play 3",
        "description": (
            "3 step solo PLAY in ordine di orario: la vincita di ogni step "
            "viene reinvestita nello step successivo"
        ),
        "target_steps": 3,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "score",
    },
    {
        "slip_key": "ladder_play_4",
        "label": "Scalata · Play 4",
        "description": (
            "4 step solo PLAY in ordine di orario: raddoppio progressivo "
            "del bankroll sullo step successivo"
        ),
        "target_steps": 4,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "score",
    },
    {
        "slip_key": "ladder_soft_4",
        "label": "Scalata · Play+Border 4",
        "description": (
            "4 step PLAY/BORDERLINE in ordine di orario: più flessibile, "
            "stesso meccanismo di reinvestimento"
        ),
        "target_steps": 4,
        "allowed_decisions": ("PLAY", "BORDERLINE"),
        "sort_mode": "score",
    },
)

# Strategie sperimentali persistite nello stesso ledger delle schedine legacy.
# Le chiavi delle schedine non iniziano deliberatamente con ``play_``: quel
# prefisso e' ancora usato dal flusso di pubblicazione ufficiale.
EXPERIMENTAL_SLIP_PROFILES: tuple[dict[str, object], ...] = (
    {
        "slip_key": "experiment_play_only_3",
        "label": "Solo PLAY · Tripla",
        "description": "3 PLAY su eventi distinti, senza diversificazione forzata per mercato",
        "target_picks": 3,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "score",
        "include_markets": DEFAULT_SLIP_MARKETS,
        "distinct_events": True,
        "force_market_diversity": False,
        "strategy_family": "play_only",
        "strategy_version": "play_only_v1",
        "is_experimental": True,
    },
    {
        "slip_key": "experiment_strong_markets_3",
        "label": "Mercati forti · Tripla",
        "description": "3 PLAY primo set su eventi distinti (regola strong_markets v1)",
        "target_picks": 3,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "score",
        "include_markets": STRONG_MARKETS_V1,
        "distinct_events": True,
        "force_market_diversity": False,
        "strategy_family": "strong_markets",
        "strategy_version": "strong_markets_v1",
        "is_experimental": True,
    },
    {
        "slip_key": "experiment_selective_2",
        "label": "Selettiva · Doppia",
        "description": (
            "Massimo 2 PLAY primo set su eventi distinti, score prudente e quota totale <= 3.20"
        ),
        "target_picks": 2,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "conservative",
        "include_markets": STRONG_MARKETS_V1,
        "distinct_events": True,
        "force_market_diversity": False,
        "max_combined_odds": 3.2,
        "strategy_family": "selective",
        "strategy_version": "selective_v1",
        "is_experimental": True,
    },
)

EXPERIMENTAL_LADDER_PROFILES: tuple[dict[str, object], ...] = (
    {
        "slip_key": "ladder_experiment_play_only_3",
        "label": "Solo PLAY · Scalata 3",
        "description": "3 step PLAY su eventi distinti e tutti i mercati",
        "target_steps": 3,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "score",
        "include_markets": DEFAULT_SLIP_MARKETS,
        "strategy_family": "play_only",
        "strategy_version": "play_only_v1",
        "is_experimental": True,
    },
    {
        "slip_key": "ladder_experiment_strong_markets_3",
        "label": "Mercati forti · Scalata 3",
        "description": "3 step PLAY primo set su eventi distinti",
        "target_steps": 3,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "score",
        "include_markets": STRONG_MARKETS_V1,
        "strategy_family": "strong_markets",
        "strategy_version": "strong_markets_v1",
        "is_experimental": True,
    },
    {
        "slip_key": "ladder_experiment_selective_3",
        "label": "Selettiva · Scalata 3",
        "description": "Fino a 3 step PLAY primo set, score prudente e quota totale <= 4.00",
        "target_steps": 3,
        "allowed_decisions": ("PLAY",),
        "sort_mode": "conservative",
        "include_markets": STRONG_MARKETS_V1,
        "max_combined_odds": 4.0,
        "strategy_family": "selective",
        "strategy_version": "selective_v1",
        "is_experimental": True,
    },
)

DEFAULT_LADDER_COUNT = len(LADDER_PROFILES)
LADDER_SLIP_KEY_PREFIX = "ladder_"


def slip_kind_from_key(slip_key: str) -> SlipKind:
    return "ladder" if str(slip_key).startswith(LADDER_SLIP_KEY_PREFIX) else "parlay"


def slip_kind_label(kind: SlipKind) -> str:
    return "Scalate" if kind == "ladder" else "Schedine"


def strategy_family_label(family: str) -> str:
    return STRATEGY_FAMILY_LABELS.get(family, family.replace("_", " ").title())


def _profile_strategy_family(profile: dict[str, object]) -> StrategyFamily:
    value = str(profile.get("strategy_family") or "generic")
    if value not in STRATEGY_FAMILY_LABELS:
        return "generic"
    return value  # type: ignore[return-value]


def _profile_strategy_version(profile: dict[str, object]) -> str:
    return str(profile.get("strategy_version") or "legacy_v1")


def _strategy_experiments_enabled(model_version: str, model_name: str) -> bool:
    return (
        model_version == STRATEGY_EXPERIMENT_MODEL_VERSION
        and model_name == STRATEGY_EXPERIMENT_MODEL_NAME
    )


def _slip_strategy_family(slip: BettingSlip) -> StrategyFamily:
    value = str(getattr(slip, "strategy_family", None) or "generic")
    if value not in STRATEGY_FAMILY_LABELS:
        return "generic"
    return value  # type: ignore[return-value]


def _slip_strategy_version(slip: BettingSlip) -> str:
    return str(getattr(slip, "strategy_version", None) or "legacy_v1")


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
    void_odds: float
    edge_absolute: float
    edge_percent: float
    expected_roi: float
    suggested_min_edge_percent: float
    min_edge_percent: float
    value_decision: str
    value_label: str
    confidence: float
    pick_score: float
    market: str = "match_winner"


@dataclass(frozen=True)
class PoolFixtureRow:
    """Minimal fixture shape shared by live ``NextFixture`` and historical ``Fixture``."""

    event_key: int
    event_date: date | None
    event_time: time | None
    tournament_name: str | None
    surface: str | None
    event_first_player: str | None
    event_second_player: str | None
    first_player_key: int | None
    second_player_key: int | None
    odds: Any
    event_status: str | None = None
    is_completed: bool = False


def _lifecycle_for_pool_fixture(
    fixture: NextFixture | PoolFixtureRow,
    *,
    event_winner: str | None = None,
) -> MatchLifecycleStatus:
    return classify_match_lifecycle(
        event_status=getattr(fixture, "event_status", None),
        event_winner=event_winner,
        is_completed=bool(getattr(fixture, "is_completed", False)),
    )


def _pool_fixtures_for_date(
    db: Session,
    slip_date: date,
    *,
    include_completed: bool = False,
) -> list[NextFixture | PoolFixtureRow]:
    """Load fixtures usable as slip candidates.

    Live generation uses only open ``NextFixture`` rows that are still
    ``upcoming`` (cancelled / postponed / abandoned / unknown / started are
    excluded once that status is known at update time). Historical replay
    (``include_completed=True``) also accepts completed next-fixtures, and if
    the rolling table no longer holds that day (moved to ``fixture``), falls
    back to ``Fixture`` rows with real odds — still excluding void-like
    statuses.
    """
    if not include_completed:
        rows = list(
            db.scalars(
                select(NextFixture)
                .where(
                    NextFixture.is_completed.is_(False),
                    NextFixture.event_date == slip_date,
                    has_real_odds(NextFixture.odds),
                )
                .order_by(
                    NextFixture.event_time.asc().nullslast(),
                    NextFixture.event_key.asc(),
                )
            ).all()
        )
        return [
            fixture
            for fixture in rows
            if is_eligible_for_slip_pool(
                _lifecycle_for_pool_fixture(fixture),
                include_completed=False,
            )
        ]

    next_rows = list(
        db.scalars(
            select(NextFixture)
            .where(
                NextFixture.event_date == slip_date,
                has_real_odds(NextFixture.odds),
            )
            .order_by(
                NextFixture.event_time.asc().nullslast(),
                NextFixture.event_key.asc(),
            )
        ).all()
    )
    if next_rows:
        return [
            fixture
            for fixture in next_rows
            if is_eligible_for_slip_pool(
                _lifecycle_for_pool_fixture(fixture),
                include_completed=True,
            )
        ]

    return [
        PoolFixtureRow(
            event_key=fixture.event_key,
            event_date=fixture.event_date,
            event_time=fixture.event_time,
            tournament_name=fixture.tournament_name,
            surface=None,
            event_first_player=fixture.event_first_player,
            event_second_player=fixture.event_second_player,
            first_player_key=fixture.first_player_key,
            second_player_key=fixture.second_player_key,
            odds=fixture.odds,
            event_status=fixture.event_status,
            is_completed=fixture.event_winner in COMPLETED_WINNERS,
        )
        for fixture in db.scalars(
            select(Fixture)
            .where(
                Fixture.event_date == slip_date,
                has_real_odds(Fixture.odds),
            )
            .order_by(
                Fixture.event_time.asc().nullslast(),
                Fixture.event_key.asc(),
            )
        ).all()
        if is_eligible_for_slip_pool(
            classify_match_lifecycle(
                event_status=fixture.event_status,
                event_winner=fixture.event_winner,
                event_final_result=fixture.event_final_result,
                is_completed=fixture.event_winner in COMPLETED_WINNERS,
            ),
            include_completed=True,
        )
    ]


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


def _fixture_odds(fixture: NextFixture | PoolFixtureRow) -> MatchWinnerOddsAverage | None:
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


def _model_artifact_exists(model_version: ModelVersion, model_name: str) -> bool:
    return (MODEL_VERSIONS[model_version].models_dir / f"{model_name}.pkl").exists()


def _resolve_betting_model_name(
    model_version: ModelVersion,
    model_name: str | None,
) -> tuple[str, str | None]:
    if model_name is not None:
        return model_name, None
    resolved = _resolve_model_name(model_version, None)
    if resolved is not None:
        return resolved, None
    return DEFAULT_MODEL_NAME, "model_selection_unavailable"


def _value_label_for_decision(decision: str) -> str:
    if decision == "PLAY":
        return "Singola con valore"
    if decision == "BORDERLINE":
        return "Quota in area void"
    return "Quota sotto valore"


def build_candidate_pool(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
    min_edge_percent: float | None = None,
    min_edge_overrides: dict[int, float] | None = None,
    include_markets: tuple[str, ...] = DEFAULT_SLIP_MARKETS,
    include_completed: bool = False,
) -> list[CandidatePick]:
    """Pool unico di candidati "a valore", potenzialmente misto tra mercati
    diversi sulla STESSA giornata (match_winner + first_set_winner +
    over_under_games: tutti hanno quote bookmaker reali, quindi edge/ROI/
    PLAY-BORDERLINE-NO BET calcolabili in modo onesto).

    La selezione a valle (``_select_picks_simple``/``_select_picks_for_tier``)
    deduplica per ``(event_key, market)``: la stessa fixture puo' quindi
    contribuire con mercati diversi nella medesima schedina, ma mai con due
    copie dello stesso mercato.

    ``include_completed=True`` is for offline historical replay: include
    completed next-fixtures and fall back to ``Fixture`` when the rolling
    table no longer holds that day. Production slip generation keeps the
    default ``False``.
    """
    candidates: list[CandidatePick] = []
    if "match_winner" in include_markets:
        candidates.extend(
            _build_match_winner_candidate_pool(
                db,
                slip_date=slip_date,
                model_version=model_version,
                model_name=model_name,
                min_edge_percent=min_edge_percent,
                min_edge_overrides=min_edge_overrides,
                include_completed=include_completed,
            )
        )
    if "first_set_winner" in include_markets:
        candidates.extend(
            _build_first_set_winner_candidate_pool(
                db,
                slip_date=slip_date,
                min_edge_percent=min_edge_percent,
                min_edge_overrides=min_edge_overrides,
                include_completed=include_completed,
            )
        )
    if "over_under_games" in include_markets:
        candidates.extend(
            _build_over_under_candidate_pool(
                db,
                slip_date=slip_date,
                min_edge_percent=min_edge_percent,
                min_edge_overrides=min_edge_overrides,
                include_completed=include_completed,
            )
        )
    candidates.sort(key=lambda candidate: candidate.pick_score, reverse=True)
    return candidates


def _build_match_winner_candidate_pool(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
    min_edge_percent: float | None = None,
    min_edge_overrides: dict[int, float] | None = None,
    include_completed: bool = False,
) -> list[CandidatePick]:
    fixtures = _pool_fixtures_for_date(
        db, slip_date, include_completed=include_completed
    )
    if not fixtures:
        return []

    prediction_by_key = _predictions_by_event_key(
        db,
        [fixture.event_key for fixture in fixtures],
        model_version,
        model_name,
    )
    overrides = min_edge_overrides or {}

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
        if odds is None or winner_odds is None or market_prob is None:
            continue
        confidence = _confidence(prediction.prob_player_1_win)
        if model_prob is None or confidence is None:
            continue

        edge = model_prob - market_prob if market_prob is not None else None
        void_odds = calculate_void_odds(model_prob)
        edge_absolute = winner_odds - void_odds
        edge_percent = (edge_absolute / void_odds) * 100.0
        expected_roi = calculate_expected_roi(winner_odds, model_prob)
        baseline_min_edge = (
            DEFAULT_MIN_EDGE_PERCENT if min_edge_percent is None else float(min_edge_percent)
        )
        suggested_min_edge = baseline_min_edge
        effective_min_edge = overrides.get(fixture.event_key, baseline_min_edge)
        value_decision = classify_single_bet_value(
            market_odds=winner_odds,
            void_odds=void_odds,
            min_edge_percent=effective_min_edge,
        )

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
                void_odds=round(void_odds, 4),
                edge_absolute=round(edge_absolute, 4),
                edge_percent=round(edge_percent, 2),
                expected_roi=round(expected_roi, 6),
                suggested_min_edge_percent=suggested_min_edge,
                min_edge_percent=round(float(effective_min_edge), 2),
                value_decision=value_decision,
                value_label=_value_label_for_decision(value_decision),
                confidence=confidence,
                pick_score=_pick_score(model_prob, edge, winner_odds),
                market="match_winner",
            )
        )

    candidates.sort(key=lambda candidate: candidate.pick_score, reverse=True)
    return candidates


def _build_first_set_winner_candidate_pool(
    db: Session,
    *,
    slip_date: date,
    min_edge_percent: float | None = None,
    min_edge_overrides: dict[int, float] | None = None,
    include_completed: bool = False,
) -> list[CandidatePick]:
    """Candidati Vincitore 1° set: predizioni gia' pubblicate con quota reale."""
    fixtures = _pool_fixtures_for_date(
        db, slip_date, include_completed=include_completed
    )
    if not fixtures:
        return []
    fixtures_by_key = {fixture.event_key: fixture for fixture in fixtures}

    published_by_event = list_latest_published_predictions_by_event_keys(
        db, list(fixtures_by_key.keys()), model_versions=[FIRST_SET_WINNER_MODEL_VERSION],
    )
    overrides = min_edge_overrides or {}
    candidates: list[CandidatePick] = []

    for event_key, rows in published_by_event.items():
        fixture = fixtures_by_key.get(event_key)
        if fixture is None or not rows:
            continue
        row = max(rows, key=lambda item: item.published_at)
        if (
            row.probability is None
            or row.odds is None
            or row.void_odds is None
            or row.selection not in COMPLETED_WINNERS
        ):
            continue

        market_prob: float | None = None
        edge: float | None = None
        odds_avg = average_first_set_winner_odds_from_record(
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
        if odds_avg is not None:
            try:
                no_vig_p1, no_vig_p2 = no_vig_market_probabilities(
                    odds_avg.avg_player_1_odds, odds_avg.avg_player_2_odds,
                )
                market_prob = no_vig_p1 if row.selection == "First Player" else no_vig_p2
                edge = float(row.probability) - market_prob
            except ValueError:
                market_prob = None

        model_prob = float(row.probability)
        odds = float(row.odds)
        void_odds = float(row.void_odds)
        edge_absolute = odds - void_odds
        edge_percent = (edge_absolute / void_odds) * 100.0
        expected_roi = calculate_expected_roi(odds, model_prob)
        baseline_min_edge = (
            DEFAULT_MIN_EDGE_PERCENT if min_edge_percent is None else float(min_edge_percent)
        )
        effective_min_edge = overrides.get(event_key, baseline_min_edge)
        value_decision = classify_single_bet_value(
            market_odds=odds,
            void_odds=void_odds,
            min_edge_percent=effective_min_edge,
        )
        winner_label = (
            fixture.event_first_player
            if row.selection == "First Player"
            else fixture.event_second_player
        ) or row.selection

        candidates.append(
            CandidatePick(
                event_key=fixture.event_key,
                event_date=fixture.event_date,
                event_time=fixture.event_time,
                tournament_name=fixture.tournament_name,
                surface=fixture.surface,
                player_1_name=fixture.event_first_player,
                player_2_name=fixture.event_second_player,
                predicted_winner=row.selection,
                predicted_winner_label=winner_label,
                model_prob=model_prob,
                market_prob=round(market_prob, 4) if market_prob is not None else None,
                edge=round(edge, 4) if edge is not None else None,
                odds=odds,
                void_odds=round(void_odds, 4),
                edge_absolute=round(edge_absolute, 4),
                edge_percent=round(edge_percent, 2),
                expected_roi=round(expected_roi, 6),
                suggested_min_edge_percent=baseline_min_edge,
                min_edge_percent=round(float(effective_min_edge), 2),
                value_decision=value_decision,
                value_label=_value_label_for_decision(value_decision),
                confidence=model_prob,
                pick_score=_pick_score(model_prob, edge, odds),
                market="first_set_winner",
            )
        )

    candidates.sort(key=lambda candidate: candidate.pick_score, reverse=True)
    return candidates


def _ou_side_and_line(selection: str | None) -> tuple[str, float] | None:
    """Estrae ("Over"|"Under", linea) da una selection tipo "Over 20.5".
    ``None`` se il testo non rispetta il formato atteso (difensivo)."""
    if not selection:
        return None
    parts = selection.split()
    if len(parts) != 2 or parts[0] not in {"Over", "Under"}:
        return None
    try:
        line = float(parts[1])
    except ValueError:
        return None
    return parts[0], line


def _build_over_under_candidate_pool(
    db: Session,
    *,
    slip_date: date,
    min_edge_percent: float | None = None,
    min_edge_overrides: dict[int, float] | None = None,
    include_completed: bool = False,
) -> list[CandidatePick]:
    """Candidati Over/Under Games: riusa le predizioni gia' pubblicate nel
    ledger ``PublishedPrediction`` (stessa fase pipeline di ``extra_market_predictions.py``,
    NON richiama il modello ML al volo qui — coerente con come il pool
    match-winner legge ``MatchPrediction`` gia' calcolato). ``market_prob``/``edge``
    (probabilita' no-vig) vengono ricalcolati dalle quote medie Over+Under della
    fixture per completezza (``PublishedPrediction`` conserva solo la quota
    della selection scelta, non entrambe)."""
    fixtures = _pool_fixtures_for_date(
        db, slip_date, include_completed=include_completed
    )
    if not fixtures:
        return []
    fixtures_by_key = {fixture.event_key: fixture for fixture in fixtures}

    published_by_event = list_latest_published_predictions_by_event_keys(
        db, list(fixtures_by_key.keys()), model_versions=[OVER_UNDER_GAMES_MODEL_VERSION],
    )
    overrides = min_edge_overrides or {}
    candidates: list[CandidatePick] = []

    for event_key, rows in published_by_event.items():
        fixture = fixtures_by_key.get(event_key)
        if fixture is None or not rows:
            continue
        row = max(rows, key=lambda item: item.published_at)
        if row.probability is None or row.odds is None or row.void_odds is None:
            continue  # niente quota reale pubblicata: non e' un candidato "a valore"

        side_line = _ou_side_and_line(row.selection)
        if side_line is None:
            continue
        side, line = side_line

        market_prob: float | None = None
        edge: float | None = None
        odds_avg = average_over_under_games_odds_from_record(
            FixtureOddsRecord(
                match_id=fixture.event_key,
                match_date=fixture.event_date,
                player_1_id=fixture.first_player_key,
                player_2_id=fixture.second_player_key,
                player_1_name=fixture.event_first_player,
                player_2_name=fixture.event_second_player,
                odds=fixture.odds,
            ),
            line=line,
        )
        if odds_avg is not None:
            try:
                no_vig_over, no_vig_under = no_vig_market_probabilities(
                    odds_avg.avg_over_odds, odds_avg.avg_under_odds,
                )
                market_prob = no_vig_over if side == "Over" else no_vig_under
                edge = float(row.probability) - market_prob
            except ValueError:
                market_prob = None

        model_prob = float(row.probability)
        odds = float(row.odds)
        void_odds = float(row.void_odds)
        edge_absolute = odds - void_odds
        edge_percent = (edge_absolute / void_odds) * 100.0
        expected_roi = calculate_expected_roi(odds, model_prob)
        baseline_min_edge = (
            DEFAULT_MIN_EDGE_PERCENT if min_edge_percent is None else float(min_edge_percent)
        )
        effective_min_edge = overrides.get(event_key, baseline_min_edge)
        value_decision = classify_single_bet_value(
            market_odds=odds,
            void_odds=void_odds,
            min_edge_percent=effective_min_edge,
        )

        candidates.append(
            CandidatePick(
                event_key=fixture.event_key,
                event_date=fixture.event_date,
                event_time=fixture.event_time,
                tournament_name=fixture.tournament_name,
                surface=fixture.surface,
                player_1_name=fixture.event_first_player,
                player_2_name=fixture.event_second_player,
                predicted_winner=row.selection,
                predicted_winner_label=f"{side} {line:g} games",
                model_prob=model_prob,
                market_prob=round(market_prob, 4) if market_prob is not None else None,
                edge=round(edge, 4) if edge is not None else None,
                odds=odds,
                void_odds=round(void_odds, 4),
                edge_absolute=round(edge_absolute, 4),
                edge_percent=round(edge_percent, 2),
                expected_roi=round(expected_roi, 6),
                suggested_min_edge_percent=baseline_min_edge,
                min_edge_percent=round(float(effective_min_edge), 2),
                value_decision=value_decision,
                value_label=_value_label_for_decision(value_decision),
                confidence=model_prob,
                pick_score=_pick_score(model_prob, edge, odds),
                market="over_under_games",
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


def _candidate_identity(candidate: CandidatePick) -> tuple[int, str]:
    """Identity persisted by ``uq_betting_slip_pick_event_market``."""
    return candidate.event_key, candidate.market


def _select_picks_simple(
    pool: list[CandidatePick],
    *,
    count: int,
    exclude_keys: set[tuple[int, str]],
    sort_key,
    extra_filter=None,
    selected_context: list[CandidatePick] | None = None,
    exclude_events: set[int] | None = None,
    distinct_events: bool = False,
    force_market_diversity: bool = True,
    max_combined_odds: float | None = None,
    initial_combined_odds: float = 1.0,
) -> list[CandidatePick]:
    blocked_events = set(exclude_events or set())
    filtered = [
        candidate
        for candidate in pool
        if _candidate_identity(candidate) not in exclude_keys
        and (not distinct_events or candidate.event_key not in blocked_events)
        and (extra_filter(candidate) if extra_filter is not None else True)
    ]
    filtered.sort(key=lambda candidate: sort_key(candidate) + _diversity_bonus(candidate, []), reverse=True)

    selected_picks: list[CandidatePick] = []
    context = list(selected_context or [])
    remaining = filtered.copy()
    while len(selected_picks) < count and remaining:
        current_selection = [*context, *selected_picks]
        used_events = blocked_events | {pick.event_key for pick in current_selection}
        used_markets = {pick.market for pick in current_selection}
        unseen_market_candidates = [
            candidate
            for candidate in remaining
            if candidate.market not in used_markets
            and (not distinct_events or candidate.event_key not in used_events)
        ]
        # Finche' esiste un mercato non ancora rappresentato, riservagli il
        # prossimo slot. In questo modo una schedina e' realmente multi-mercato
        # quando il tier dispone di candidati idonei, senza inventare pick che
        # non superano il filtro PLAY/BORDERLINE/NO BET del profilo.
        eligible = (
            unseen_market_candidates
            if force_market_diversity and unseen_market_candidates
            else remaining
        )
        if distinct_events:
            eligible = [candidate for candidate in eligible if candidate.event_key not in used_events]
        if max_combined_odds is not None:
            current_odds = initial_combined_odds
            for pick in current_selection:
                current_odds *= float(pick.odds or 1.0)
            eligible = [
                candidate
                for candidate in eligible
                if current_odds * float(candidate.odds or 1.0) <= max_combined_odds
            ]
        if not eligible:
            break
        eligible.sort(
            key=lambda candidate: sort_key(candidate) + _diversity_bonus(candidate, current_selection),
            reverse=True,
        )
        next_pick = eligible[0]
        remaining.remove(next_pick)
        if _candidate_identity(next_pick) in {
            _candidate_identity(pick) for pick in current_selection
        }:
            continue
        selected_picks.append(next_pick)
    return selected_picks


def _combined_odds(picks: list[CandidatePick]) -> float:
    total = 1.0
    for pick in picks:
        if pick.odds is not None:
            total *= pick.odds
    return round(total, 4)


def _sort_key_for_mode(sort_mode: str):
    if sort_mode == "confidence":
        return lambda candidate: candidate.confidence
    if sort_mode == "edge":
        return lambda candidate: candidate.edge or 0.0
    if sort_mode == "conservative":
        return lambda candidate: (
            float(candidate.expected_roi or 0.0)
            + float(candidate.confidence or 0.0) * 0.15
            - max(float(candidate.odds or 1.0) - 1.8, 0.0) * 0.1
        )
    return lambda candidate: candidate.pick_score


def _select_picks_for_tier(
    candidates: list[CandidatePick],
    *,
    count: int,
    exclude_keys: set[tuple[int, str]],
    allowed_decisions: tuple[str, ...],
    sort_key,
    include_markets: tuple[str, ...] = DEFAULT_SLIP_MARKETS,
    exclude_events: set[int] | None = None,
    distinct_events: bool = False,
    force_market_diversity: bool = True,
    max_combined_odds: float | None = None,
    initial_combined_odds: float = 1.0,
) -> list[CandidatePick]:
    """Fill a slip preferring a mix of decision states when the tier allows them."""
    allowed_set = set(allowed_decisions)

    def base_filter(candidate: CandidatePick) -> bool:
        return (
            candidate.value_decision in allowed_set
            and candidate.market in include_markets
        )

    if allowed_set == {"PLAY"}:
        return _select_picks_simple(
            candidates,
            count=count,
            exclude_keys=exclude_keys,
            sort_key=sort_key,
            extra_filter=base_filter,
            exclude_events=exclude_events,
            distinct_events=distinct_events,
            force_market_diversity=force_market_diversity,
            max_combined_odds=max_combined_odds,
            initial_combined_odds=initial_combined_odds,
        )

    selected: list[CandidatePick] = []
    used = set(exclude_keys)
    secondary = [decision for decision in allowed_decisions if decision != "PLAY"]
    # Reserve roughly one slot per non-PLAY state when available.
    for decision in secondary:
        if len(selected) >= count:
            break
        picks = _select_picks_simple(
            candidates,
            count=1,
            exclude_keys=used,
            sort_key=sort_key,
            extra_filter=lambda candidate, decision=decision: (
                candidate.value_decision == decision
                and candidate.market in include_markets
            ),
            selected_context=selected,
            exclude_events=exclude_events,
            distinct_events=distinct_events,
            force_market_diversity=force_market_diversity,
            max_combined_odds=max_combined_odds,
            initial_combined_odds=initial_combined_odds,
        )
        for pick in picks:
            selected.append(pick)
            used.add(_candidate_identity(pick))

    remaining = count - len(selected)
    if remaining > 0:
        fillers = _select_picks_simple(
            candidates,
            count=remaining,
            exclude_keys=used,
            sort_key=sort_key,
            extra_filter=base_filter,
            selected_context=selected,
            exclude_events=exclude_events,
            distinct_events=distinct_events,
            force_market_diversity=force_market_diversity,
            max_combined_odds=max_combined_odds,
            initial_combined_odds=initial_combined_odds,
        )
        selected.extend(fillers)

    return selected[:count]


def _select_picks_for_profile(
    candidates: list[CandidatePick],
    *,
    profile: dict[str, object],
    count: int,
    exclude_keys: set[tuple[int, str]] | None = None,
    exclude_events: set[int] | None = None,
    initial_combined_odds: float = 1.0,
) -> list[CandidatePick]:
    allowed = tuple(profile["allowed_decisions"])  # type: ignore[arg-type]
    include_markets = tuple(
        profile.get("include_markets") or DEFAULT_SLIP_MARKETS
    )  # type: ignore[arg-type]
    max_combined_odds = profile.get("max_combined_odds")
    return _select_picks_for_tier(
        candidates,
        count=count,
        exclude_keys=set(exclude_keys or set()),
        allowed_decisions=allowed,
        sort_key=_sort_key_for_mode(str(profile.get("sort_mode") or "score")),
        include_markets=include_markets,
        exclude_events=exclude_events,
        distinct_events=bool(profile.get("distinct_events", False)),
        force_market_diversity=bool(profile.get("force_market_diversity", True)),
        max_combined_odds=(
            float(max_combined_odds) if max_combined_odds is not None else None
        ),
        initial_combined_odds=initial_combined_odds,
    )


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
    used_keys_by_tier: dict[tuple[str, ...], set[tuple[int, str]]] = defaultdict(set)

    for profile in profiles:
        target = min(int(profile["target_picks"]), picks_per_slip)
        slip_key = str(profile["slip_key"])
        allowed = tuple(profile["allowed_decisions"])  # type: ignore[arg-type]
        sort_mode = str(profile.get("sort_mode") or "score")
        sort_key = _sort_key_for_mode(sort_mode)
        tier_used = used_keys_by_tier[allowed]

        picks = _select_picks_for_tier(
            candidates,
            count=target,
            exclude_keys=tier_used,
            allowed_decisions=allowed,
            sort_key=sort_key,
        )
        if len(picks) < target:
            warnings.append(
                f"Schedina '{profile['label']}': solo {len(picks)}/{target} pick disponibili."
            )
        # Serve almeno una doppia: non persistiamo schedine monogamba.
        if len(picks) < 2:
            continue

        tier_used.update(_candidate_identity(pick) for pick in picks)
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


def generate_experimental_slips(
    candidates: list[CandidatePick],
) -> tuple[list[GeneratedSlip], list[str]]:
    """Generate one independent parlay for each experimental family."""
    warnings: list[str] = []
    generated: list[GeneratedSlip] = []
    for profile in EXPERIMENTAL_SLIP_PROFILES:
        target = int(profile["target_picks"])
        picks = _select_picks_for_profile(
            candidates,
            profile=profile,
            count=target,
        )
        if len(picks) < target:
            warnings.append(
                f"Schedina '{profile['label']}': solo {len(picks)}/{target} pick disponibili."
            )
        if len(picks) < 2:
            continue
        generated.append(
            GeneratedSlip(
                slip_key=str(profile["slip_key"]),
                label=str(profile["label"]),
                description=str(profile["description"]),
                picks=tuple(picks),
                combined_odds=_combined_odds(picks),
            )
        )
    return generated, warnings


def _select_ladder_steps(
    candidates: list[CandidatePick],
    *,
    count: int,
    exclude_keys: set[tuple[int, str]],
    exclude_events: set[int],
    allowed_decisions: tuple[str, ...],
    sort_key,
    include_markets: tuple[str, ...] = DEFAULT_SLIP_MARKETS,
    max_combined_odds: float | None = None,
    initial_combined_odds: float = 1.0,
) -> list[CandidatePick]:
    """Pick ``count`` singles on distinct fixtures, then order by kickoff."""
    pool = [
        candidate
        for candidate in candidates
        if candidate.value_decision in allowed_decisions
        and candidate.market in include_markets
        and _candidate_identity(candidate) not in exclude_keys
        and candidate.event_key not in exclude_events
        and candidate.odds is not None
        and candidate.odds > 1.0
    ]
    pool.sort(
        key=lambda candidate: sort_key(candidate) + _diversity_bonus(candidate, []),
        reverse=True,
    )

    selected: list[CandidatePick] = []
    used_events: set[int] = set()
    remaining = pool.copy()
    combined_odds = initial_combined_odds
    while len(selected) < count and remaining:
        current = [*selected]
        remaining.sort(
            key=lambda candidate: sort_key(candidate)
            + _diversity_bonus(candidate, current),
            reverse=True,
        )
        pick = remaining.pop(0)
        if pick.event_key in used_events:
            continue
        projected_odds = combined_odds * float(pick.odds or 1.0)
        if max_combined_odds is not None and projected_odds > max_combined_odds:
            continue
        selected.append(pick)
        combined_odds = projected_odds
        used_events.add(pick.event_key)
        remaining = [item for item in remaining if item.event_key not in used_events]

    selected.sort(
        key=lambda candidate: (
            candidate.event_time is None,
            candidate.event_time or time.max,
            candidate.event_key,
            candidate.market,
        )
    )
    return selected


def generate_ladders(
    candidates: list[CandidatePick],
    *,
    ladder_count: int = DEFAULT_LADDER_COUNT,
) -> tuple[list[GeneratedSlip], list[str]]:
    """Build progressive stake ladders from the same value candidate pool."""
    warnings: list[str] = []
    if not candidates:
        return [], ["Nessun candidato disponibile per generare scalate."]

    profiles = list(LADDER_PROFILES[:ladder_count])
    generated: list[GeneratedSlip] = []
    used_keys: set[tuple[int, str]] = set()
    used_events: set[int] = set()

    for profile in profiles:
        target = int(profile["target_steps"])
        allowed = tuple(profile["allowed_decisions"])  # type: ignore[arg-type]
        sort_mode = str(profile.get("sort_mode") or "score")
        sort_key = _sort_key_for_mode(sort_mode)
        picks = _select_ladder_steps(
            candidates,
            count=target,
            exclude_keys=used_keys,
            exclude_events=used_events,
            allowed_decisions=allowed,
            sort_key=sort_key,
        )
        if len(picks) < target:
            warnings.append(
                f"Scalata '{profile['label']}': solo {len(picks)}/{target} step disponibili."
            )
        if len(picks) < 2:
            continue

        used_keys.update(_candidate_identity(pick) for pick in picks)
        used_events.update(pick.event_key for pick in picks)
        generated.append(
            GeneratedSlip(
                slip_key=str(profile["slip_key"]),
                label=str(profile["label"]),
                description=str(profile["description"]),
                picks=tuple(picks),
                combined_odds=_combined_odds(picks),
            )
        )

    if len(generated) < ladder_count:
        warnings.append(
            f"Solo {len(generated)} scalate generate: candidati insufficienti."
        )

    return generated, warnings


def generate_experimental_ladders(
    candidates: list[CandidatePick],
) -> tuple[list[GeneratedSlip], list[str]]:
    """Generate one independent ladder for each experimental family."""
    warnings: list[str] = []
    generated: list[GeneratedSlip] = []
    for profile in EXPERIMENTAL_LADDER_PROFILES:
        target = int(profile["target_steps"])
        include_markets = tuple(
            profile.get("include_markets") or DEFAULT_SLIP_MARKETS
        )  # type: ignore[arg-type]
        max_combined_odds = profile.get("max_combined_odds")
        picks = _select_ladder_steps(
            candidates,
            count=target,
            exclude_keys=set(),
            exclude_events=set(),
            allowed_decisions=tuple(profile["allowed_decisions"]),  # type: ignore[arg-type]
            sort_key=_sort_key_for_mode(str(profile.get("sort_mode") or "score")),
            include_markets=include_markets,
            max_combined_odds=(
                float(max_combined_odds) if max_combined_odds is not None else None
            ),
        )
        if len(picks) < target:
            warnings.append(
                f"Scalata '{profile['label']}': solo {len(picks)}/{target} step disponibili."
            )
        if len(picks) < 2:
            continue
        generated.append(
            GeneratedSlip(
                slip_key=str(profile["slip_key"]),
                label=str(profile["label"]),
                description=str(profile["description"]),
                picks=tuple(picks),
                combined_odds=_combined_odds(picks),
            )
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


def _ladder_slips_exist(
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
            BettingSlip.slip_key.startswith(LADDER_SLIP_KEY_PREFIX),
        )
    )
    return int(count or 0) > 0


def _get_or_create_slip_day_window(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
    settings: Settings,
    now: datetime | None = None,
) -> tuple[BettingSlipDay, bool, datetime]:
    """Return registry row, whether additions are allowed, and UTC-naive now."""
    local_now = _local_now(settings, now)
    now_utc = _utc_now_naive(local_now)
    row = db.scalar(
        select(BettingSlipDay)
        .where(
            BettingSlipDay.slip_date == slip_date,
            BettingSlipDay.model_version == model_version,
            BettingSlipDay.model_name == model_name,
        )
        .with_for_update()
    )
    close_at = _pool_close_utc_naive(slip_date, settings=settings)
    if row is None:
        row = BettingSlipDay(
            slip_date=slip_date,
            model_version=model_version,
            model_name=model_name,
            candidate_pool_size=0,
            slip_count=0,
            fixture_count=_count_upcoming_fixtures_on_date(db, slip_date),
            generated_at=now_utc,
            updated_at=now_utc,
            pool_closes_at=close_at,
            pool_locked_at=None,
        )
        db.add(row)
        db.flush()
    elif row.pool_closes_at is None:
        row.pool_closes_at = close_at

    effective_close = row.pool_closes_at or close_at
    additions_allowed = (
        row.pool_locked_at is None
        and slip_date >= local_now.date()
        and now_utc < effective_close
    )
    if not additions_allowed and row.pool_locked_at is None:
        row.pool_locked_at = now_utc
    row.updated_at = now_utc
    db.flush()
    return row, additions_allowed, now_utc


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
    now_utc: datetime | None = None,
) -> None:
    now = now_utc or _utc_now_naive()
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
        if row.pool_locked_at is None:
            row.candidate_pool_size = max(row.candidate_pool_size, candidate_pool_size)
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
    model_version: ModelVersion = DEFAULT_ACTIVE_MATCH_WINNER_VERSION,
    model_name: str | None = None,
) -> BettingSlipCalendarResponse:
    today = date.today()
    resolved_model_name, model_warning = _resolve_betting_model_name(model_version, model_name)

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
    profile_map = _profile_by_slip_key()
    for slip_data in generated_slips:
        profile = profile_map.get(slip_data.slip_key, {})
        slip = BettingSlip(
            slip_date=slip_date,
            slip_key=slip_data.slip_key,
            label=slip_data.label,
            description=slip_data.description,
            model_version=model_version,
            model_name=model_name,
            strategy_family=_profile_strategy_family(profile),
            strategy_version=_profile_strategy_version(profile),
            is_experimental=bool(profile.get("is_experimental", False)),
            pick_count=len(slip_data.picks),
            combined_odds=slip_data.combined_odds,
            generated_at=generated_at,
        )
        db.add(slip)
        db.flush()
        for index, pick in enumerate(slip_data.picks):
            _add_candidate_pick(db, slip=slip, pick=pick, sort_order=index)
    db.commit()


def _add_candidate_pick(
    db: Session,
    *,
    slip: BettingSlip,
    pick: CandidatePick,
    sort_order: int,
) -> BettingSlipPick:
    row = BettingSlipPick(
        betting_slip_id=slip.id,
        event_key=pick.event_key,
        market=pick.market,
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
        void_odds=pick.void_odds,
        edge_absolute=pick.edge_absolute,
        edge_percent=pick.edge_percent,
        expected_roi=pick.expected_roi,
        suggested_min_edge_percent=pick.suggested_min_edge_percent,
        min_edge_percent=pick.min_edge_percent,
        value_decision=pick.value_decision,
        value_label=pick.value_label,
        confidence=pick.confidence,
        pick_score=pick.pick_score,
        sort_order=sort_order,
        outcome="pending",
        settled_at=None,
    )
    db.add(row)
    return row


def _profile_by_slip_key() -> dict[str, dict[str, object]]:
    return {
        str(profile["slip_key"]): profile
        for profile in (
            *SLIP_PROFILES,
            *LADDER_PROFILES,
            *EXPERIMENTAL_SLIP_PROFILES,
            *EXPERIMENTAL_LADDER_PROFILES,
        )
    }


def _persist_new_profile_slip(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
    profile: dict[str, object],
    picks: list[CandidatePick],
) -> BettingSlip:
    generated_at = _utc_now_naive()
    slip = BettingSlip(
        slip_date=slip_date,
        slip_key=str(profile["slip_key"]),
        label=str(profile["label"]),
        description=str(profile["description"]),
        model_version=model_version,
        model_name=model_name,
        strategy_family=_profile_strategy_family(profile),
        strategy_version=_profile_strategy_version(profile),
        is_experimental=bool(profile.get("is_experimental", False)),
        pick_count=len(picks),
        combined_odds=_combined_odds(picks),
        generated_at=generated_at,
    )
    db.add(slip)
    db.flush()
    for index, pick in enumerate(picks):
        _add_candidate_pick(db, slip=slip, pick=pick, sort_order=index)
    return slip


def _append_candidates_to_slip(
    db: Session,
    *,
    slip: BettingSlip,
    additions: list[CandidatePick],
) -> int:
    if not additions:
        return 0
    next_order = max((pick.sort_order for pick in slip.picks), default=-1) + 1
    for offset, pick in enumerate(additions):
        _add_candidate_pick(
            db,
            slip=slip,
            pick=pick,
            sort_order=next_order + offset,
        )
    all_odds = [float(pick.odds) for pick in slip.picks if pick.odds is not None]
    all_odds.extend(float(pick.odds) for pick in additions if pick.odds is not None)
    combined = 1.0
    for odd in all_odds:
        combined *= odd
    slip.pick_count = len(slip.picks) + len(additions)
    slip.combined_odds = round(combined, 4)
    return len(additions)


def _merge_candidates_into_slips(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
    candidates: list[CandidatePick],
    slip_count: int,
    picks_per_slip: int,
) -> tuple[int, list[str]]:
    """Append candidates to missing capacity without replacing persisted picks."""
    warnings: list[str] = []
    existing = _load_slips(
        db,
        slip_date=slip_date,
        model_version=model_version,
        model_name=model_name,
    )
    existing_by_key = {slip.slip_key: slip for slip in existing}
    profile_map = _profile_by_slip_key()
    added = 0

    used_by_tier: dict[tuple[str, ...], set[tuple[int, str]]] = defaultdict(set)
    for slip in existing:
        profile = profile_map.get(slip.slip_key)
        if (
            profile is None
            or slip.slip_key.startswith(LADDER_SLIP_KEY_PREFIX)
            or _slip_strategy_family(slip) != "generic"
        ):
            continue
        allowed = tuple(profile["allowed_decisions"])  # type: ignore[arg-type]
        used_by_tier[allowed].update((pick.event_key, pick.market) for pick in slip.picks)

    for profile in SLIP_PROFILES[:slip_count]:
        slip_key = str(profile["slip_key"])
        slip = existing_by_key.get(slip_key)
        target = min(int(profile["target_picks"]), picks_per_slip)
        active_count = (
            sum(pick.outcome != "void" for pick in slip.picks)
            if slip is not None
            else 0
        )
        remaining = max(target - active_count, 0)
        if remaining == 0:
            continue
        allowed = tuple(profile["allowed_decisions"])  # type: ignore[arg-type]
        tier_used = used_by_tier[allowed]
        selected = _select_picks_for_tier(
            candidates,
            count=remaining,
            exclude_keys=tier_used,
            allowed_decisions=allowed,
            sort_key=_sort_key_for_mode(str(profile.get("sort_mode") or "score")),
        )
        if slip is None:
            if len(selected) < 2:
                warnings.append(
                    f"Schedina '{profile['label']}': solo {len(selected)}/{target} pick disponibili."
                )
                continue
            slip = _persist_new_profile_slip(
                db,
                slip_date=slip_date,
                model_version=model_version,
                model_name=model_name,
                profile=profile,
                picks=selected,
            )
            existing_by_key[slip_key] = slip
            added += len(selected)
        else:
            added += _append_candidates_to_slip(db, slip=slip, additions=selected)
        tier_used.update(_candidate_identity(pick) for pick in selected)
        if active_count + len(selected) < target:
            warnings.append(
                f"Schedina '{profile['label']}': solo {active_count + len(selected)}/{target} pick attive disponibili."
            )

    if _strategy_experiments_enabled(model_version, model_name):
        for profile in EXPERIMENTAL_SLIP_PROFILES:
            slip_key = str(profile["slip_key"])
            slip = existing_by_key.get(slip_key)
            target = int(profile["target_picks"])
            active_picks = (
                [pick for pick in slip.picks if pick.outcome != "void"]
                if slip is not None
                else []
            )
            remaining = max(target - len(active_picks), 0)
            if remaining == 0:
                continue
            existing_keys = (
                {(pick.event_key, pick.market) for pick in slip.picks}
                if slip is not None
                else set()
            )
            existing_events = (
                {pick.event_key for pick in slip.picks}
                if slip is not None
                else set()
            )
            initial_odds = 1.0
            for pick in active_picks:
                initial_odds *= float(pick.odds or 1.0)
            selected = _select_picks_for_profile(
                candidates,
                profile=profile,
                count=remaining,
                exclude_keys=existing_keys,
                exclude_events=existing_events,
                initial_combined_odds=initial_odds,
            )
            if slip is None:
                if len(selected) < 2:
                    warnings.append(
                        f"Schedina '{profile['label']}': solo {len(selected)}/{target} pick disponibili."
                    )
                    continue
                slip = _persist_new_profile_slip(
                    db,
                    slip_date=slip_date,
                    model_version=model_version,
                    model_name=model_name,
                    profile=profile,
                    picks=selected,
                )
                existing_by_key[slip_key] = slip
                added += len(selected)
            else:
                added += _append_candidates_to_slip(db, slip=slip, additions=selected)
            if len(active_picks) + len(selected) < target:
                warnings.append(
                    f"Schedina '{profile['label']}': solo {len(active_picks) + len(selected)}/{target} pick attive disponibili."
                )

    ladder_used_keys: set[tuple[int, str]] = set()
    ladder_used_events: set[int] = set()
    for slip in existing:
        if (
            not slip.slip_key.startswith(LADDER_SLIP_KEY_PREFIX)
            or _slip_strategy_family(slip) != "generic"
        ):
            continue
        ladder_used_keys.update((pick.event_key, pick.market) for pick in slip.picks)
        ladder_used_events.update(pick.event_key for pick in slip.picks)

    for profile in LADDER_PROFILES:
        slip_key = str(profile["slip_key"])
        slip = existing_by_key.get(slip_key)
        target = int(profile["target_steps"])
        active_count = (
            sum(pick.outcome != "void" for pick in slip.picks)
            if slip is not None
            else 0
        )
        remaining = max(target - active_count, 0)
        if remaining == 0:
            continue
        selected = _select_ladder_steps(
            candidates,
            count=remaining,
            exclude_keys=ladder_used_keys,
            exclude_events=ladder_used_events,
            allowed_decisions=tuple(profile["allowed_decisions"]),  # type: ignore[arg-type]
            sort_key=_sort_key_for_mode(str(profile.get("sort_mode") or "score")),
        )
        if slip is not None and slip.picks:
            last_time = max(
                (pick.event_time for pick in slip.picks if pick.event_time is not None),
                default=None,
            )
            if last_time is not None:
                selected = [
                    pick
                    for pick in selected
                    if pick.event_time is not None and pick.event_time >= last_time
                ]
        if slip is None:
            if len(selected) < 2:
                warnings.append(
                    f"Scalata '{profile['label']}': solo {len(selected)}/{target} step disponibili."
                )
                continue
            slip = _persist_new_profile_slip(
                db,
                slip_date=slip_date,
                model_version=model_version,
                model_name=model_name,
                profile=profile,
                picks=selected,
            )
            existing_by_key[slip_key] = slip
            added += len(selected)
        else:
            added += _append_candidates_to_slip(db, slip=slip, additions=selected)
        ladder_used_keys.update(_candidate_identity(pick) for pick in selected)
        ladder_used_events.update(pick.event_key for pick in selected)
        if active_count + len(selected) < target:
            warnings.append(
                f"Scalata '{profile['label']}': solo {active_count + len(selected)}/{target} step attivi disponibili."
            )

    if _strategy_experiments_enabled(model_version, model_name):
        for profile in EXPERIMENTAL_LADDER_PROFILES:
            slip_key = str(profile["slip_key"])
            slip = existing_by_key.get(slip_key)
            target = int(profile["target_steps"])
            active_picks = (
                [pick for pick in slip.picks if pick.outcome != "void"]
                if slip is not None
                else []
            )
            remaining = max(target - len(active_picks), 0)
            if remaining == 0:
                continue
            existing_keys = (
                {(pick.event_key, pick.market) for pick in slip.picks}
                if slip is not None
                else set()
            )
            existing_events = (
                {pick.event_key for pick in slip.picks}
                if slip is not None
                else set()
            )
            initial_odds = 1.0
            for pick in active_picks:
                initial_odds *= float(pick.odds or 1.0)
            include_markets = tuple(
                profile.get("include_markets") or DEFAULT_SLIP_MARKETS
            )  # type: ignore[arg-type]
            max_combined_odds = profile.get("max_combined_odds")
            selected = _select_ladder_steps(
                candidates,
                count=remaining,
                exclude_keys=existing_keys,
                exclude_events=existing_events,
                allowed_decisions=tuple(profile["allowed_decisions"]),  # type: ignore[arg-type]
                sort_key=_sort_key_for_mode(str(profile.get("sort_mode") or "score")),
                include_markets=include_markets,
                max_combined_odds=(
                    float(max_combined_odds) if max_combined_odds is not None else None
                ),
                initial_combined_odds=initial_odds,
            )
            if slip is not None and slip.picks:
                last_time = max(
                    (pick.event_time for pick in slip.picks if pick.event_time is not None),
                    default=None,
                )
                if last_time is not None:
                    selected = [
                        pick
                        for pick in selected
                        if pick.event_time is not None and pick.event_time >= last_time
                    ]
            if slip is None:
                if len(selected) < 2:
                    warnings.append(
                        f"Scalata '{profile['label']}': solo {len(selected)}/{target} step disponibili."
                    )
                    continue
                slip = _persist_new_profile_slip(
                    db,
                    slip_date=slip_date,
                    model_version=model_version,
                    model_name=model_name,
                    profile=profile,
                    picks=selected,
                )
                existing_by_key[slip_key] = slip
                added += len(selected)
            else:
                added += _append_candidates_to_slip(db, slip=slip, additions=selected)
            if len(active_picks) + len(selected) < target:
                warnings.append(
                    f"Scalata '{profile['label']}': solo {len(active_picks) + len(selected)}/{target} step attivi disponibili."
                )

    db.commit()
    return added, warnings


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
) -> tuple[dict[int, MatchPrediction], dict[int, Fixture], dict[int, NextFixture]]:
    if not event_keys:
        return {}, {}, {}

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
    next_fixtures = {
        fixture.event_key: fixture
        for fixture in db.scalars(
            select(NextFixture).where(NextFixture.event_key.in_(event_keys))
        ).all()
    }
    return predictions, fixtures, next_fixtures


def _resolve_match_lifecycle(
    event_key: int,
    *,
    fixtures: dict[int, Fixture],
    next_fixtures: dict[int, NextFixture],
    actual_winner: str | None,
):
    fixture = fixtures.get(event_key)
    next_fixture = next_fixtures.get(event_key)
    event_status = None
    event_final_result = None
    event_live = None
    is_completed = None
    if fixture is not None:
        event_status = fixture.event_status
        event_final_result = fixture.event_final_result
        event_live = fixture.event_live
        is_completed = fixture.event_winner in COMPLETED_WINNERS
    elif next_fixture is not None:
        event_status = next_fixture.event_status
        event_final_result = (
            next_fixture.live_score.get("final_result")
            if isinstance(next_fixture.live_score, dict)
            else None
        )
        event_live = next_fixture.event_live
        is_completed = bool(next_fixture.is_completed)

    lifecycle = classify_match_lifecycle(
        event_status=event_status,
        event_winner=actual_winner or (
            next_fixture.event_winner if next_fixture is not None else None
        ),
        event_final_result=event_final_result,
        event_live=event_live,
        is_completed=is_completed,
    )
    return lifecycle, event_status


def _score_snapshot_for_event(
    event_key: int,
    *,
    fixtures: dict[int, Fixture],
    next_fixtures: dict[int, NextFixture],
) -> dict | None:
    """Return one score snapshot for both live and completed fixtures."""
    fixture = fixtures.get(event_key)
    if fixture is not None:
        snapshot = {
            "sets": fixture.scores or [],
            "current_game": fixture.event_game_result,
            "server": fixture.event_serve,
            "final_result": fixture.event_final_result,
            "status": fixture.event_status,
        }
        if any(value not in (None, "", [], {}) for value in snapshot.values()):
            return snapshot

    next_fixture = next_fixtures.get(event_key)
    if next_fixture is not None and isinstance(next_fixture.live_score, dict):
        return next_fixture.live_score
    return None


def _resolve_actual_winner(
    pick: BettingSlipPick,
    predictions: dict[int, MatchPrediction],
    fixtures: dict[int, Fixture],
    next_fixtures: dict[int, NextFixture] | None = None,
) -> str | None:
    """Vincitore REALE del match (First/Second Player), indipendentemente dal
    mercato scommesso su questo pick: serve a determinare il lifecycle della
    partita (``_resolve_match_lifecycle``), non l'esito del pick stesso."""
    prediction = predictions.get(pick.event_key)
    if prediction is not None and prediction.actual_winner in COMPLETED_WINNERS:
        return prediction.actual_winner

    fixture = fixtures.get(pick.event_key)
    if fixture is not None and fixture.event_winner in COMPLETED_WINNERS:
        return fixture.event_winner

    next_fixture = (next_fixtures or {}).get(pick.event_key)
    if next_fixture is not None and next_fixture.event_winner in COMPLETED_WINNERS:
        return next_fixture.event_winner

    return None


def _resolve_over_under_actual_result(
    pick: BettingSlipPick,
    fixtures: dict[int, Fixture],
) -> tuple[str | None, bool]:
    """Esito reale ("Over"/"Under") per un pick over_under_games, ricavato dal
    punteggio set-by-set reale (``score_parser``). ``has_result=False`` quando
    lo score non e' ancora disponibile/valido (match non finito, ritiro,
    anomalia): il pick resta pending o viene voidato in base al lifecycle,
    MAI forzato a won/lost senza un conteggio game affidabile."""
    fixture = fixtures.get(pick.event_key)
    if fixture is None:
        return None, False
    parsed = parse_fixture_score(
        match_id=pick.event_key,
        scores=fixture.scores,
        event_game_result=fixture.event_game_result,
    )
    if not parsed.is_valid_for_training:
        return None, False
    side_line = _ou_side_and_line(pick.predicted_winner)
    line = side_line[1] if side_line else OU_DEFAULT_LINE
    is_over = target_over_line(parsed.total_games, line)
    if is_over is None:
        return None, False
    return ("Over" if is_over else "Under"), True


def _resolve_first_set_actual_result(
    pick: BettingSlipPick,
    fixtures: dict[int, Fixture],
) -> tuple[str | None, bool]:
    """Esito reale 1° set ("First Player"/"Second Player") da score set-by-set."""
    fixture = fixtures.get(pick.event_key)
    if fixture is None:
        return None, False
    parsed = parse_fixture_score(
        match_id=pick.event_key,
        scores=fixture.scores,
        event_game_result=fixture.event_game_result,
    )
    if not parsed.is_valid_for_training or parsed.first_set_winner is None:
        return None, False
    if parsed.first_set_winner == "player_1":
        return "First Player", True
    if parsed.first_set_winner == "player_2":
        return "Second Player", True
    return None, False


def _resolve_pick_actual_result(
    pick: BettingSlipPick,
    *,
    predictions: dict[int, MatchPrediction],
    fixtures: dict[int, Fixture],
    next_fixtures: dict[int, NextFixture] | None = None,
) -> tuple[str | None, bool]:
    """Esito REALE del mercato specifico di questo pick (generico su
    ``pick.market``): ("First Player"/"Second Player", has_result) per
    match_winner / first_set_winner, ("Over"/"Under", has_result) per
    over_under_games."""
    if pick.market == "over_under_games":
        return _resolve_over_under_actual_result(pick, fixtures)
    if pick.market == "first_set_winner":
        return _resolve_first_set_actual_result(pick, fixtures)
    actual_winner = _resolve_actual_winner(
        pick, predictions, fixtures, next_fixtures
    )
    return actual_winner, actual_winner in COMPLETED_WINNERS


def _actual_winner_label(
    actual_result: str | None,
    pick: BettingSlipPick,
) -> str | None:
    if actual_result is None:
        return None
    if pick.market == "over_under_games":
        return actual_result  # "Over"/"Under" e' gia' leggibile di per se'
    return _winner_label(actual_result, pick.player_1_name, pick.player_2_name)


def _resolve_pick_status(
    pick: BettingSlipPick,
    actual_result: str | None,
    *,
    match_lifecycle_status: MatchLifecycleStatus | None = None,
    has_result: bool | None = None,
) -> tuple[PickStatus, bool | None]:
    lifecycle = match_lifecycle_status or "upcoming"
    predicted = pick.predicted_winner
    if pick.market == "over_under_games":
        side_line = _ou_side_and_line(predicted)
        predicted = side_line[0] if side_line else predicted
    settlement = settle_simulated_bet(
        lifecycle=lifecycle,
        predicted_winner=predicted,
        actual_winner=actual_result,
        market_odds=pick.odds,
        has_result=has_result,
        postponed_as_void=True,
    )
    return settlement.outcome, settlement.is_correct


def sync_betting_slip_pick_outcomes(
    db: Session,
    *,
    slip_date: date | None = None,
    model_version: ModelVersion | None = None,
    model_name: str | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Persist terminal pick outcomes without changing existing selections."""
    stmt = select(BettingSlip).options(selectinload(BettingSlip.picks))
    if slip_date is not None:
        stmt = stmt.where(BettingSlip.slip_date == slip_date)
    if model_version is not None:
        stmt = stmt.where(BettingSlip.model_version == model_version)
    if model_name is not None:
        stmt = stmt.where(BettingSlip.model_name == model_name)
    slips = list(db.scalars(stmt.order_by(BettingSlip.id.asc())).all())
    summary = {"checked": 0, "settled": 0, "won": 0, "lost": 0, "void": 0}
    if not slips:
        return summary

    event_keys = sorted({pick.event_key for slip in slips for pick in slip.picks})
    contexts: dict[
        tuple[str, str],
        tuple[dict[int, MatchPrediction], dict[int, Fixture], dict[int, NextFixture]],
    ] = {}
    for slip in slips:
        key = (slip.model_version, slip.model_name)
        if key not in contexts:
            contexts[key] = _load_outcome_context(
                db,
                event_keys,
                slip.model_version,  # type: ignore[arg-type]
                slip.model_name,
            )

    settled_at = _utc_now_naive(now)
    for slip in slips:
        predictions, fixtures, next_fixtures = contexts[
            (slip.model_version, slip.model_name)
        ]
        for pick in slip.picks:
            summary["checked"] += 1
            if pick.outcome in {"won", "lost", "void"}:
                continue
            actual_winner = _resolve_actual_winner(
                pick, predictions, fixtures, next_fixtures
            )
            lifecycle, _event_status = _resolve_match_lifecycle(
                pick.event_key,
                fixtures=fixtures,
                next_fixtures=next_fixtures,
                actual_winner=actual_winner,
            )
            actual_result, has_result = _resolve_pick_actual_result(
                pick,
                predictions=predictions,
                fixtures=fixtures,
                next_fixtures=next_fixtures,
            )
            outcome, _is_correct = _resolve_pick_status(
                pick,
                actual_result,
                match_lifecycle_status=lifecycle,
                has_result=has_result,
            )
            if outcome not in {"won", "lost", "void"}:
                continue
            pick.outcome = outcome
            pick.settled_at = settled_at
            summary["settled"] += 1
            summary[outcome] += 1

    if summary["settled"]:
        db.commit()
    return summary


def _resolve_slip_status(pick_statuses: list[PickStatus]) -> SlipStatus:
    return resolve_slip_status_from_picks(pick_statuses)


def _effective_combined_odds(picks: list[BettingSlipPickRead]) -> float | None:
    active = [pick for pick in picks if pick.pick_status != "void" and pick.odds is not None]
    if not active:
        return None
    product = 1.0
    for pick in active:
        product *= float(pick.odds)
    return round(product, 4)


def _resolve_pick_value_fields(
    pick: BettingSlipPick,
    *,
    min_edge_percent: float | None = None,
) -> dict[str, float | str | None]:
    stored_min_edge = getattr(pick, "min_edge_percent", None)
    stored_suggested = getattr(pick, "suggested_min_edge_percent", None)
    effective_min_edge = (
        min_edge_percent
        if min_edge_percent is not None
        else stored_min_edge
        if stored_min_edge is not None
        else DEFAULT_MIN_EDGE_PERCENT
    )
    if pick.model_prob is None or pick.odds is None:
        return {
            "void_odds": None,
            "edge_absolute": None,
            "edge_percent": None,
            "expected_roi": None,
            "suggested_min_edge_percent": stored_suggested,
            "min_edge_percent": stored_min_edge,
            "value_decision": None,
            "value_label": None,
        }

    # Always reclassify with the requested margin; stored value_decision may be stale.
    void_odds = (
        float(pick.void_odds)
        if pick.void_odds is not None
        else calculate_void_odds(pick.model_prob)
    )
    edge_absolute = pick.odds - void_odds
    edge_percent = (edge_absolute / void_odds) * 100.0
    expected_roi = (
        float(pick.expected_roi)
        if pick.expected_roi is not None
        else calculate_expected_roi(pick.odds, pick.model_prob)
    )
    value_decision = classify_single_bet_value(
        market_odds=pick.odds,
        void_odds=void_odds,
        min_edge_percent=float(effective_min_edge),
    )
    return {
        "void_odds": round(void_odds, 4),
        "edge_absolute": round(edge_absolute, 4),
        "edge_percent": round(edge_percent, 2),
        "expected_roi": round(expected_roi, 6),
        "suggested_min_edge_percent": stored_suggested,
        "min_edge_percent": round(float(effective_min_edge), 2),
        "value_decision": value_decision,
        "value_label": _value_label_for_decision(value_decision),
    }


def _pick_read(
    pick: BettingSlipPick,
    *,
    predictions: dict[int, MatchPrediction],
    fixtures: dict[int, Fixture],
    next_fixtures: dict[int, NextFixture],
    min_edge_percent: float | None = None,
) -> BettingSlipPickRead:
    match_actual_winner = _resolve_actual_winner(
        pick, predictions, fixtures, next_fixtures
    )
    lifecycle, event_status = _resolve_match_lifecycle(
        pick.event_key,
        fixtures=fixtures,
        next_fixtures=next_fixtures,
        actual_winner=match_actual_winner,
    )
    actual_result, has_result = _resolve_pick_actual_result(
        pick,
        predictions=predictions,
        fixtures=fixtures,
        next_fixtures=next_fixtures,
    )
    derived_status, is_correct = _resolve_pick_status(
        pick,
        actual_result,
        match_lifecycle_status=lifecycle,
        has_result=has_result,
    )
    stored_status = getattr(pick, "outcome", None)
    pick_status: PickStatus = (
        stored_status
        if stored_status in {"won", "lost", "void"}
        else derived_status
    )
    if pick_status == "won":
        is_correct = True
    elif pick_status == "lost":
        is_correct = False
    elif pick_status == "void":
        is_correct = None
    value_fields = _resolve_pick_value_fields(pick, min_edge_percent=min_edge_percent)
    void_reason = None
    if pick_status == "void":
        void_reason = match_lifecycle_label(lifecycle)
    return BettingSlipPickRead(
        event_key=pick.event_key,
        market=pick.market,
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
        void_odds=value_fields["void_odds"],
        edge_absolute=value_fields["edge_absolute"],
        edge_percent=value_fields["edge_percent"],
        expected_roi=value_fields["expected_roi"],
        suggested_min_edge_percent=value_fields["suggested_min_edge_percent"],
        min_edge_percent=value_fields["min_edge_percent"],
        value_decision=value_fields["value_decision"],
        value_label=value_fields["value_label"],
        confidence=pick.confidence,
        pick_score=pick.pick_score,
        pick_status=pick_status,
        outcome=pick_status,
        actual_winner_label=_actual_winner_label(actual_result, pick),
        is_correct=is_correct,
        match_lifecycle_status=lifecycle,
        match_lifecycle_label=match_lifecycle_label(lifecycle),
        event_status=event_status,
        live_score=_score_snapshot_for_event(
            pick.event_key,
            fixtures=fixtures,
            next_fixtures=next_fixtures,
        ),
        settled_at=getattr(pick, "settled_at", None),
        void_reason=void_reason,
    )


def _slip_read(
    slip: BettingSlip,
    *,
    predictions: dict[int, MatchPrediction],
    fixtures: dict[int, Fixture],
    next_fixtures: dict[int, NextFixture],
    stake: float,
    min_edge_percent: float | None = None,
) -> BettingSlipRead:
    pick_reads = [
        _pick_read(
            pick,
            predictions=predictions,
            fixtures=fixtures,
            next_fixtures=next_fixtures,
            min_edge_percent=min_edge_percent,
        )
        for pick in sorted(slip.picks, key=lambda item: item.sort_order)
    ]
    pick_statuses = [pick.pick_status for pick in pick_reads]
    slip_status = _resolve_slip_status(pick_statuses)
    picks_won = sum(1 for status in pick_statuses if status == "won")
    picks_lost = sum(1 for status in pick_statuses if status == "lost")
    picks_pending = sum(1 for status in pick_statuses if status == "pending")
    picks_void = sum(1 for status in pick_statuses if status == "void")
    combined_probability_estimate = 1.0
    for pick in pick_reads:
        if pick.pick_status == "void":
            continue
        if pick.model_prob is not None:
            combined_probability_estimate *= pick.model_prob
    combined_probability_estimate = round(combined_probability_estimate, 6)
    effective_combined_odds = _effective_combined_odds(pick_reads)
    if slip_status == "void":
        potential_return = round(stake, 2)
        potential_profit = 0.0
    else:
        odds_for_potential = (
            effective_combined_odds
            if effective_combined_odds is not None
            else slip.combined_odds
        )
        potential_return = round(stake * odds_for_potential, 2)
        potential_profit = round(potential_return - stake, 2)
    resolved_combined_odds = 1.0
    for pick in pick_reads:
        if pick.pick_status == "won" and pick.odds is not None:
            resolved_combined_odds *= pick.odds
    resolved_combined_odds = round(resolved_combined_odds, 4) if picks_won else None
    theoretical_profit_if_won = potential_profit if slip_status == "won" else None
    slip_kind = slip_kind_from_key(slip.slip_key)
    if slip_kind == "ladder":
        pick_reads = _annotate_ladder_step_stakes(pick_reads, stake=stake)

    return BettingSlipRead(
        id=slip.slip_key,
        slip_key=slip.slip_key,
        label=slip.label,
        description=slip.description,
        slip_kind=slip_kind,
        strategy_family=_slip_strategy_family(slip),
        strategy_version=_slip_strategy_version(slip),
        is_experimental=bool(getattr(slip, "is_experimental", False)),
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
        picks_void=picks_void,
        picks_total=len(pick_reads),
        resolved_combined_odds=resolved_combined_odds,
        effective_combined_odds=effective_combined_odds,
        theoretical_profit_if_won=theoretical_profit_if_won,
        generated_at=slip.generated_at,
    )


def _annotate_ladder_step_stakes(
    picks: list[BettingSlipPickRead],
    *,
    stake: float,
) -> list[BettingSlipPickRead]:
    """Attach progressive stake path (void carries stake; loss stops compounding)."""
    annotated: list[BettingSlipPickRead] = []
    running_stake = float(stake)
    chain_alive = True
    for index, pick in enumerate(picks):
        step_stake = round(running_stake, 2) if chain_alive else 0.0
        step_return: float | None = None
        if chain_alive and pick.pick_status != "void" and pick.odds is not None:
            step_return = round(step_stake * pick.odds, 2)
        elif chain_alive and pick.pick_status == "void":
            step_return = step_stake

        annotated.append(
            pick.model_copy(
                update={
                    "ladder_step_index": index + 1,
                    "ladder_step_stake": step_stake,
                    "ladder_step_return_if_won": step_return,
                }
            )
        )

        if not chain_alive:
            continue
        if pick.pick_status == "lost":
            chain_alive = False
            running_stake = 0.0
        elif pick.pick_status == "void":
            continue
        elif pick.odds is not None:
            # Pending/won: show theoretical path assuming the step holds.
            running_stake = step_stake * pick.odds
    return annotated


def _build_daily_response(
    db: Session,
    *,
    slip_date: date,
    model_version: ModelVersion,
    model_name: str,
    stake: float,
    candidate_pool_size: int,
    warnings: list[str],
    min_edge_percent: float | None = None,
) -> BettingSlipsDailyResponse:
    slips = _load_slips(
        db,
        slip_date=slip_date,
        model_version=model_version,
        model_name=model_name,
    )
    event_keys = [pick.event_key for slip in slips for pick in slip.picks]
    predictions, fixtures, next_fixtures = _load_outcome_context(db, event_keys, model_version, model_name)
    slip_reads = [
        _slip_read(
            slip,
            predictions=predictions,
            fixtures=fixtures,
            next_fixtures=next_fixtures,
            stake=stake,
            min_edge_percent=min_edge_percent,
        )
        for slip in slips
    ]
    pending_picks_count = sum(
        pick.pick_status == "pending" for slip in slip_reads for pick in slip.picks
    )
    response_warnings = list(warnings)
    if slip_date < date.today() and pending_picks_count:
        response_warnings.append(
            "historical_outcomes_missing: alcuni esiti non sono disponibili nel database; usa Aggiorna dopo aver ripristinato l'import API."
        )
    return BettingSlipsDailyResponse(
        date=slip_date,
        model_version=model_version,
        model_name=model_name,
        match_winner_model_version=model_version,
        match_winner_model_name=model_name,
        market_models=_slip_market_models(model_version, model_name),
        stake=stake,
        candidate_pool_size=candidate_pool_size,
        slips=slip_reads,
        warnings=response_warnings,
    )


def get_daily_betting_slips(
    db: Session,
    *,
    slip_date: date | None = None,
    model_version: ModelVersion = DEFAULT_ACTIVE_MATCH_WINNER_VERSION,
    model_name: str | None = None,
    stake: float = DEFAULT_STAKE,
    slip_count: int = DEFAULT_SLIP_COUNT,
    picks_per_slip: int = DEFAULT_PICKS_PER_SLIP,
    min_edge_percent: float | None = None,
    min_edge_overrides: dict[int, float] | None = None,
    regenerate: bool = False,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> BettingSlipsDailyResponse:
    settings = settings or get_settings()
    target_date = slip_date or _local_now(settings, now).date()
    resolved_model_name, model_warning = _resolve_betting_model_name(model_version, model_name)

    warnings: list[str] = [model_warning] if model_warning else []
    registry, additions_allowed, now_utc = _get_or_create_slip_day_window(
        db,
        slip_date=target_date,
        model_version=model_version,
        model_name=resolved_model_name,
        settings=settings,
        now=now,
    )
    candidate_pool_size = int(registry.candidate_pool_size or 0)

    # Settle cancellations/postponements before calculating remaining profile
    # capacity. A void leg stays persisted but may be followed by a replacement
    # while the daily window is still open.
    sync_betting_slip_pick_outcomes(
        db,
        slip_date=target_date,
        model_version=model_version,
        model_name=resolved_model_name,
        now=now_utc,
    )

    if additions_allowed:
        candidates = build_candidate_pool(
            db,
            slip_date=target_date,
            model_version=model_version,
            model_name=resolved_model_name,
            min_edge_percent=min_edge_percent,
            min_edge_overrides=min_edge_overrides,
        )
        candidate_pool_size = max(candidate_pool_size, len(candidates))
        _added, merge_warnings = _merge_candidates_into_slips(
            db,
            slip_date=target_date,
            model_version=model_version,
            model_name=resolved_model_name,
            candidates=candidates,
            slip_count=slip_count,
            picks_per_slip=picks_per_slip,
        )
        warnings.extend(merge_warnings)
        if not candidates and not _slips_exist(
            db,
            slip_date=target_date,
            model_version=model_version,
            model_name=resolved_model_name,
        ):
            warnings.append(
                "Nessuna pick disponibile: servono previsioni e quote bookmaker per le partite del giorno."
            )
    else:
        warnings.append("Pool giornaliero chiuso: le pick persistite non vengono modificate.")
        if regenerate and target_date < _local_now(settings, now).date():
            warnings.append(
                "Schedine storiche mantenute: il pool append-only non modifica giornate concluse."
            )

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
        now_utc=now_utc,
    )

    return _build_daily_response(
        db,
        slip_date=target_date,
        model_version=model_version,
        model_name=resolved_model_name,
        stake=stake,
        candidate_pool_size=candidate_pool_size,
        warnings=warnings,
        min_edge_percent=min_edge_percent,
    )


def refresh_betting_slips(
    db: Session,
    *,
    slip_date: date | None = None,
    model_version: ModelVersion = DEFAULT_ACTIVE_MATCH_WINNER_VERSION,
    model_name: str | None = None,
    stake: float = DEFAULT_STAKE,
    days_back: int = 1,
    min_edge_percent: float | None = None,
    min_edge_overrides: dict[int, float] | None = None,
    regenerate: bool = True,
) -> BettingSlipsRefreshResponse:
    from backend.src.app.services.imports import import_played_fixtures, refresh_matches

    target_date = slip_date or date.today()
    resolved_model_name, model_warning = _resolve_betting_model_name(model_version, model_name)
    effective_days_back = max(days_back, max((date.today() - target_date).days, 0))
    import_summary = import_played_fixtures(db, days_back=effective_days_back)
    if _model_artifact_exists(model_version, resolved_model_name):
        refresh_summary = refresh_matches(
            db,
            days_forward=10,
            days_back_next=3,
            model_version=model_version,
            model_name=resolved_model_name,
            force_next_import=False,
        )
    else:
        refresh_summary = {
            "next_fixtures_imported": False,
            "predictions_summary": {
                "model_version": model_version,
                "model_name": resolved_model_name,
                "skipped": True,
                "reason": "model_artifact_missing",
            },
        }

    daily = get_daily_betting_slips(
        db,
        slip_date=target_date,
        model_version=model_version,
        model_name=resolved_model_name,
        stake=stake,
        min_edge_percent=min_edge_percent,
        min_edge_overrides=min_edge_overrides,
        regenerate=regenerate,
    )
    if model_warning:
        daily.warnings.append(model_warning)
    if not _model_artifact_exists(model_version, resolved_model_name):
        daily.warnings.append("model_artifact_missing")

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
    odds = (
        slip.effective_combined_odds
        if slip.effective_combined_odds is not None
        else slip.combined_odds
    )
    return slip_profit_units(
        slip_status=slip.slip_status,
        stake=stake,
        effective_combined_odds=odds,
    )


def _new_strategy_stats_bucket() -> dict[str, Any]:
    return {
        "slips_won": 0,
        "slips_lost": 0,
        "slips_pending": 0,
        "slips_void": 0,
        "slips_total": 0,
        "picks_total": 0,
        "picks_won": 0,
        "picks_lost": 0,
        "picks_pending": 0,
        "picks_void": 0,
        "profit_units": 0.0,
        "resolved_count": 0,
        "strategy_versions": set(),
        "is_experimental": False,
    }


def _record_strategy_stats(
    bucket: dict[str, Any],
    *,
    slip_read: BettingSlipRead,
    strategy_version: str,
    is_experimental: bool,
    stake: float,
) -> float | None:
    bucket["slips_total"] = int(bucket["slips_total"]) + 1
    bucket["picks_total"] = int(bucket["picks_total"]) + slip_read.picks_total
    bucket["picks_won"] = int(bucket["picks_won"]) + slip_read.picks_won
    bucket["picks_lost"] = int(bucket["picks_lost"]) + slip_read.picks_lost
    bucket["picks_pending"] = int(bucket["picks_pending"]) + slip_read.picks_pending
    bucket["picks_void"] = int(bucket["picks_void"]) + slip_read.picks_void
    bucket["strategy_versions"].add(strategy_version)
    bucket["is_experimental"] = bool(bucket["is_experimental"]) or is_experimental
    if slip_read.slip_status == "won":
        bucket["slips_won"] = int(bucket["slips_won"]) + 1
    elif slip_read.slip_status == "lost":
        bucket["slips_lost"] = int(bucket["slips_lost"]) + 1
    elif slip_read.slip_status == "void":
        bucket["slips_void"] = int(bucket["slips_void"]) + 1
    else:
        bucket["slips_pending"] = int(bucket["slips_pending"]) + 1
    if slip_read.slip_status not in {"won", "lost"}:
        return None
    profit = _slip_profit_units(slip_read, stake)
    bucket["profit_units"] = float(bucket["profit_units"]) + profit
    bucket["resolved_count"] = int(bucket["resolved_count"]) + 1
    return profit


def _build_strategy_stats_rows(
    strategy_stats: dict[tuple[StrategyFamily, SlipKind], dict[str, Any]],
    strategy_daily_profits: dict[
        tuple[StrategyFamily, SlipKind], dict[date, list[float]]
    ],
    strategy_pending_days: dict[tuple[StrategyFamily, SlipKind], set[date]],
    *,
    stake: float,
) -> list[BettingSlipStatsStrategy]:
    family_order = {family: index for index, family in enumerate(STRATEGY_FAMILY_LABELS)}
    rows: list[BettingSlipStatsStrategy] = []
    for (family, kind), stats in sorted(
        strategy_stats.items(),
        key=lambda item: (
            item[0][1] == "ladder",
            family_order.get(item[0][0], 99),
        ),
    ):
        daily_buckets = strategy_daily_profits.get((family, kind), {})
        pending_days = strategy_pending_days.get((family, kind), set())
        daily_profit = sum(
            sum(profits) / len(profits)
            for day, profits in daily_buckets.items()
            if profits and day not in pending_days
        )
        comparable_days = sum(
            1
            for day, profits in daily_buckets.items()
            if profits and day not in pending_days
        )
        resolved_count = int(stats["resolved_count"])
        rows.append(
            BettingSlipStatsStrategy(
                strategy_family=family,
                label=strategy_family_label(family),
                slip_kind=kind,
                strategy_versions=sorted(str(value) for value in stats["strategy_versions"]),
                is_experimental=bool(stats["is_experimental"]),
                slips_total=int(stats["slips_total"]),
                slips_won=int(stats["slips_won"]),
                slips_lost=int(stats["slips_lost"]),
                slips_pending=int(stats["slips_pending"]),
                slips_void=int(stats["slips_void"]),
                slip_win_rate_pct=_pct(
                    int(stats["slips_won"]),
                    int(stats["slips_won"]) + int(stats["slips_lost"]),
                ),
                picks_total=int(stats["picks_total"]),
                picks_won=int(stats["picks_won"]),
                picks_lost=int(stats["picks_lost"]),
                picks_pending=int(stats["picks_pending"]),
                picks_void=int(stats["picks_void"]),
                pick_hit_rate_pct=_pct(
                    int(stats["picks_won"]),
                    int(stats["picks_won"]) + int(stats["picks_lost"]),
                ),
                theoretical_profit_units=round(float(stats["profit_units"]), 2),
                theoretical_roi_pct=(
                    round(float(stats["profit_units"]) / (stake * resolved_count) * 100, 1)
                    if resolved_count and stake
                    else None
                ),
                daily_portfolio_profit_units=round(daily_profit, 2),
                daily_portfolio_roi_pct=(
                    round(daily_profit / (stake * comparable_days) * 100, 1)
                    if comparable_days and stake
                    else None
                ),
                comparable_days=comparable_days,
            )
        )
    return rows


def compute_betting_slip_stats(
    db: Session,
    *,
    model_version: ModelVersion = DEFAULT_ACTIVE_MATCH_WINNER_VERSION,
    model_name: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    stake: float = DEFAULT_STAKE,
    all_time: bool = False,
) -> BettingSlipStatsResponse:
    today = date.today()
    resolved_model_name, _model_warning = _resolve_betting_model_name(model_version, model_name)
    if all_time:
        resolved_from = db.scalar(
            select(func.min(BettingSlip.slip_date)).where(
                BettingSlip.model_version == model_version,
                BettingSlip.model_name == resolved_model_name,
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
                BettingSlip.model_name == resolved_model_name,
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
    next_fixtures: dict[int, NextFixture] = {}
    for model_name_for_context in model_names or {resolved_model_name}:
        model_predictions, model_fixtures, model_next_fixtures = _load_outcome_context(
            db,
            event_keys,
            model_version,
            model_name_for_context,
        )
        predictions.update(model_predictions)
        fixtures.update(model_fixtures)
        next_fixtures.update(model_next_fixtures)

    slips_by_date: dict[date, list[BettingSlipRead]] = defaultdict(list)
    profile_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "slips_won": 0,
            "slips_lost": 0,
            "slips_pending": 0,
            "slips_void": 0,
            "slips_total": 0,
            "slip_kind": "parlay",
            "strategy_family": "generic",
            "strategy_version": "legacy_v1",
            "is_experimental": False,
            "profit_units": 0.0,
            "resolved_count": 0,
        }
    )
    strategy_stats: dict[
        tuple[StrategyFamily, SlipKind], dict[str, Any]
    ] = defaultdict(_new_strategy_stats_bucket)
    strategy_daily_profits: dict[
        tuple[StrategyFamily, SlipKind], dict[date, list[float]]
    ] = defaultdict(lambda: defaultdict(list))
    strategy_pending_days: dict[tuple[StrategyFamily, SlipKind], set[date]] = defaultdict(set)
    kind_stats: dict[SlipKind, dict[str, float | int]] = {
        "parlay": {
            "slips_won": 0,
            "slips_lost": 0,
            "slips_pending": 0,
            "slips_void": 0,
            "slips_total": 0,
            "picks_total": 0,
            "picks_won": 0,
            "picks_lost": 0,
            "picks_pending": 0,
            "picks_void": 0,
            "profit_units": 0.0,
            "resolved_count": 0,
        },
        "ladder": {
            "slips_won": 0,
            "slips_lost": 0,
            "slips_pending": 0,
            "slips_void": 0,
            "slips_total": 0,
            "picks_total": 0,
            "picks_won": 0,
            "picks_lost": 0,
            "picks_pending": 0,
            "picks_void": 0,
            "profit_units": 0.0,
            "resolved_count": 0,
        },
    }

    summary_slips_won = 0
    summary_slips_lost = 0
    summary_slips_pending = 0
    summary_slips_void = 0
    summary_picks_won = 0
    summary_picks_lost = 0
    summary_picks_pending = 0
    summary_picks_void = 0
    summary_picks_total = 0

    for slip in slips:
        slip_read = _slip_read(
            slip,
            predictions=predictions,
            fixtures=fixtures,
            next_fixtures=next_fixtures,
            stake=stake,
        )
        slips_by_date[slip.slip_date].append(slip_read)

        profile = profile_stats[slip.slip_key]
        profile["label"] = slip.label
        profile["slip_kind"] = slip_kind_from_key(slip.slip_key)
        profile["strategy_family"] = _slip_strategy_family(slip)
        profile["strategy_version"] = _slip_strategy_version(slip)
        profile["is_experimental"] = bool(getattr(slip, "is_experimental", False))
        profile["slips_total"] = int(profile["slips_total"]) + 1
        if slip_read.slip_status == "won":
            profile["slips_won"] = int(profile["slips_won"]) + 1
            summary_slips_won += 1
        elif slip_read.slip_status == "lost":
            profile["slips_lost"] = int(profile["slips_lost"]) + 1
            summary_slips_lost += 1
        elif slip_read.slip_status == "void":
            profile["slips_void"] = int(profile["slips_void"]) + 1
            summary_slips_void += 1
        else:
            profile["slips_pending"] = int(profile["slips_pending"]) + 1
            summary_slips_pending += 1
        if slip_read.slip_status in {"won", "lost"}:
            profile["profit_units"] = float(profile["profit_units"]) + _slip_profit_units(
                slip_read, stake
            )
            profile["resolved_count"] = int(profile["resolved_count"]) + 1

        summary_picks_won += slip_read.picks_won
        summary_picks_lost += slip_read.picks_lost
        summary_picks_pending += slip_read.picks_pending
        summary_picks_void += slip_read.picks_void
        summary_picks_total += slip_read.picks_total

        kind_bucket = kind_stats[slip_read.slip_kind]
        kind_bucket["slips_total"] = int(kind_bucket["slips_total"]) + 1
        kind_bucket["picks_total"] = int(kind_bucket["picks_total"]) + slip_read.picks_total
        kind_bucket["picks_won"] = int(kind_bucket["picks_won"]) + slip_read.picks_won
        kind_bucket["picks_lost"] = int(kind_bucket["picks_lost"]) + slip_read.picks_lost
        kind_bucket["picks_pending"] = int(kind_bucket["picks_pending"]) + slip_read.picks_pending
        kind_bucket["picks_void"] = int(kind_bucket["picks_void"]) + slip_read.picks_void
        if slip_read.slip_status == "won":
            kind_bucket["slips_won"] = int(kind_bucket["slips_won"]) + 1
        elif slip_read.slip_status == "lost":
            kind_bucket["slips_lost"] = int(kind_bucket["slips_lost"]) + 1
        elif slip_read.slip_status == "void":
            kind_bucket["slips_void"] = int(kind_bucket["slips_void"]) + 1
        else:
            kind_bucket["slips_pending"] = int(kind_bucket["slips_pending"]) + 1
        if slip_read.slip_status in {"won", "lost"}:
            kind_bucket["profit_units"] = float(kind_bucket["profit_units"]) + _slip_profit_units(
                slip_read, stake
            )
            kind_bucket["resolved_count"] = int(kind_bucket["resolved_count"]) + 1

        strategy_key = (_slip_strategy_family(slip), slip_read.slip_kind)
        strategy_profit = _record_strategy_stats(
            strategy_stats[strategy_key],
            slip_read=slip_read,
            strategy_version=_slip_strategy_version(slip),
            is_experimental=bool(getattr(slip, "is_experimental", False)),
            stake=stake,
        )
        if strategy_profit is not None:
            strategy_daily_profits[strategy_key][slip.slip_date].append(strategy_profit)
        elif slip_read.slip_status == "pending":
            strategy_pending_days[strategy_key].add(slip.slip_date)

    days: list[BettingSlipStatsDay] = []
    current = resolved_from
    while current <= resolved_to:
        day_slips = slips_by_date.get(current, [])
        day_slips_won = sum(1 for slip in day_slips if slip.slip_status == "won")
        day_slips_lost = sum(1 for slip in day_slips if slip.slip_status == "lost")
        day_slips_pending = sum(1 for slip in day_slips if slip.slip_status == "pending")
        day_slips_void = sum(1 for slip in day_slips if slip.slip_status == "void")
        day_picks_won = sum(slip.picks_won for slip in day_slips)
        day_picks_lost = sum(slip.picks_lost for slip in day_slips)
        day_picks_pending = sum(slip.picks_pending for slip in day_slips)
        day_picks_void = sum(slip.picks_void for slip in day_slips)
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
                slips_void=day_slips_void,
                picks_total=day_picks_total,
                picks_won=day_picks_won,
                picks_lost=day_picks_lost,
                picks_pending=day_picks_pending,
                picks_void=day_picks_void,
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
        sum(
            _slip_profit_units(slip, stake)
            for slips in slips_by_date.values()
            for slip in slips
            if slip.slip_status in {"won", "lost"}
        ),
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
            slip_kind=(
                "ladder"
                if stats.get("slip_kind") == "ladder"
                else "parlay"
            ),
            strategy_family=str(stats["strategy_family"]),
            strategy_version=str(stats["strategy_version"]),
            is_experimental=bool(stats["is_experimental"]),
            slips_won=int(stats["slips_won"]),
            slips_lost=int(stats["slips_lost"]),
            slips_pending=int(stats["slips_pending"]),
            slips_void=int(stats["slips_void"]),
            slips_total=int(stats["slips_total"]),
            slip_win_rate_pct=_pct(
                int(stats["slips_won"]),
                int(stats["slips_won"]) + int(stats["slips_lost"]),
            ),
            theoretical_profit_units=round(float(stats["profit_units"]), 2),
            theoretical_roi_pct=(
                round(
                    float(stats["profit_units"])
                    / (stake * int(stats["resolved_count"]))
                    * 100,
                    1,
                )
                if int(stats["resolved_count"]) and stake
                else None
            ),
        )
        for slip_key, stats in sorted(
            profile_stats.items(),
            key=lambda item: (
                item[1].get("slip_kind") != "ladder",
                str(item[1].get("label") or item[0]),
            ),
        )
    ]
    by_kind = [
        BettingSlipStatsKind(
            slip_kind=kind,
            label=slip_kind_label(kind),
            slips_total=int(stats["slips_total"]),
            slips_won=int(stats["slips_won"]),
            slips_lost=int(stats["slips_lost"]),
            slips_pending=int(stats["slips_pending"]),
            slips_void=int(stats["slips_void"]),
            slip_win_rate_pct=_pct(
                int(stats["slips_won"]),
                int(stats["slips_won"]) + int(stats["slips_lost"]),
            ),
            picks_total=int(stats["picks_total"]),
            picks_won=int(stats["picks_won"]),
            picks_lost=int(stats["picks_lost"]),
            picks_pending=int(stats["picks_pending"]),
            picks_void=int(stats["picks_void"]),
            pick_hit_rate_pct=_pct(
                int(stats["picks_won"]),
                int(stats["picks_won"]) + int(stats["picks_lost"]),
            ),
            theoretical_profit_units=round(float(stats["profit_units"]), 2),
            theoretical_roi_pct=(
                round(
                    (float(stats["profit_units"]) / (stake * int(stats["resolved_count"])))
                    * 100,
                    1,
                )
                if int(stats["resolved_count"]) and stake
                else None
            ),
        )
        for kind, stats in kind_stats.items()
        if int(stats["slips_total"]) > 0
    ]
    by_strategy = _build_strategy_stats_rows(
        strategy_stats,
        strategy_daily_profits,
        strategy_pending_days,
        stake=stake,
    )

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
            slips_void=summary_slips_void,
            picks_total=summary_picks_total,
            picks_won=summary_picks_won,
            picks_lost=summary_picks_lost,
            picks_pending=summary_picks_pending,
            picks_void=summary_picks_void,
            slip_win_rate_pct=_pct(summary_slips_won, total_resolved_slips),
            pick_hit_rate_pct=_pct(summary_picks_won, total_resolved_picks),
            theoretical_profit_units=total_profit_units,
            theoretical_roi_pct=round((total_profit_units / total_stake) * 100, 1)
            if total_stake
            else None,
            by_profile=by_profile,
            by_kind=by_kind,
            by_strategy=by_strategy,
        ),
    )


def compute_betting_slip_model_stats(
    db: Session,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    stake: float = DEFAULT_STAKE,
    all_time: bool = False,
) -> BettingSlipModelStatsResponse:
    today = date.today()
    if all_time:
        resolved_from = db.scalar(select(func.min(BettingSlip.slip_date)))
        resolved_to = today
        if resolved_from is None:
            resolved_from = today
    else:
        resolved_to = to_date or today
        resolved_from = from_date or (today - timedelta(days=30))

    combinations = db.execute(
        select(
            BettingSlip.model_version,
            BettingSlip.model_name,
            func.min(BettingSlip.slip_date),
            func.max(BettingSlip.slip_date),
        )
        .where(
            BettingSlip.slip_date >= resolved_from,
            BettingSlip.slip_date <= resolved_to,
        )
        .group_by(BettingSlip.model_version, BettingSlip.model_name)
        .order_by(BettingSlip.model_version.asc(), BettingSlip.model_name.asc())
    ).all()

    rows: list[BettingSlipModelStatsRow] = []
    for model_version, model_name, first_date, last_date in combinations:
        stats = compute_betting_slip_stats(
            db,
            model_version=model_version,
            model_name=model_name,
            from_date=resolved_from,
            to_date=resolved_to,
            stake=stake,
            all_time=False,
        )
        summary = stats.summary
        rows.append(
            BettingSlipModelStatsRow(
                model_version=model_version,
                model_name=model_name,
                slips_total=summary.slips_total,
                slips_won=summary.slips_won,
                slips_lost=summary.slips_lost,
                slips_pending=summary.slips_pending,
                slips_void=summary.slips_void,
                slip_win_rate_pct=summary.slip_win_rate_pct,
                picks_total=summary.picks_total,
                picks_won=summary.picks_won,
                picks_lost=summary.picks_lost,
                picks_pending=summary.picks_pending,
                picks_void=summary.picks_void,
                pick_hit_rate_pct=summary.pick_hit_rate_pct,
                theoretical_profit_units=summary.theoretical_profit_units,
                theoretical_roi_pct=summary.theoretical_roi_pct,
                first_date=first_date,
                last_date=last_date,
            )
        )

    by_market = _aggregate_slip_picks_by_market(
        db,
        from_date=resolved_from,
        to_date=resolved_to,
        stake=stake,
    )
    by_kind, by_profile, by_strategy = _aggregate_slip_stats_by_kind_and_profile(
        db,
        from_date=resolved_from,
        to_date=resolved_to,
        stake=stake,
    )

    return BettingSlipModelStatsResponse(
        from_date=resolved_from,
        to_date=resolved_to,
        stake=stake,
        rows=rows,
        by_market=by_market,
        by_kind=by_kind,
        by_profile=by_profile,
        by_strategy=by_strategy,
    )


def _aggregate_slip_stats_by_kind_and_profile(
    db: Session,
    *,
    from_date: date,
    to_date: date,
    stake: float,
) -> tuple[
    list[BettingSlipStatsKind],
    list[BettingSlipStatsProfile],
    list[BettingSlipStatsStrategy],
]:
    """Cross-model aggregates for Schedine vs Scalate and profile labels."""
    slips = list(
        db.scalars(
            select(BettingSlip)
            .options(selectinload(BettingSlip.picks))
            .where(
                BettingSlip.slip_date >= from_date,
                BettingSlip.slip_date <= to_date,
            )
            .order_by(BettingSlip.slip_date.asc(), BettingSlip.id.asc())
        ).all()
    )
    if not slips:
        return [], [], []

    event_keys = [pick.event_key for slip in slips for pick in slip.picks]
    predictions: dict[int, MatchPrediction] = {}
    fixtures: dict[int, Fixture] = {}
    next_fixtures: dict[int, NextFixture] = {}
    for model_version, model_name in {
        (slip.model_version, slip.model_name) for slip in slips
    }:
        model_predictions, model_fixtures, model_next_fixtures = _load_outcome_context(
            db,
            event_keys,
            model_version,  # type: ignore[arg-type]
            model_name,
        )
        predictions.update(model_predictions)
        fixtures.update(model_fixtures)
        next_fixtures.update(model_next_fixtures)

    kind_stats: dict[SlipKind, dict[str, float | int]] = {
        "parlay": {
            "slips_won": 0,
            "slips_lost": 0,
            "slips_pending": 0,
            "slips_void": 0,
            "slips_total": 0,
            "picks_total": 0,
            "picks_won": 0,
            "picks_lost": 0,
            "picks_pending": 0,
            "picks_void": 0,
            "profit_units": 0.0,
            "resolved_count": 0,
        },
        "ladder": {
            "slips_won": 0,
            "slips_lost": 0,
            "slips_pending": 0,
            "slips_void": 0,
            "slips_total": 0,
            "picks_total": 0,
            "picks_won": 0,
            "picks_lost": 0,
            "picks_pending": 0,
            "picks_void": 0,
            "profit_units": 0.0,
            "resolved_count": 0,
        },
    }
    profile_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "slips_won": 0,
            "slips_lost": 0,
            "slips_pending": 0,
            "slips_void": 0,
            "slips_total": 0,
            "slip_kind": "parlay",
            "label": "",
            "strategy_family": "generic",
            "strategy_version": "legacy_v1",
            "is_experimental": False,
            "profit_units": 0.0,
            "resolved_count": 0,
        }
    )
    strategy_stats: dict[
        tuple[StrategyFamily, SlipKind], dict[str, Any]
    ] = defaultdict(_new_strategy_stats_bucket)
    strategy_daily_profits: dict[
        tuple[StrategyFamily, SlipKind], dict[date, list[float]]
    ] = defaultdict(lambda: defaultdict(list))
    strategy_pending_days: dict[tuple[StrategyFamily, SlipKind], set[date]] = defaultdict(set)

    for slip in slips:
        slip_read = _slip_read(
            slip,
            predictions=predictions,
            fixtures=fixtures,
            next_fixtures=next_fixtures,
            stake=stake,
        )
        kind = slip_read.slip_kind
        kind_bucket = kind_stats[kind]
        kind_bucket["slips_total"] = int(kind_bucket["slips_total"]) + 1
        kind_bucket["picks_total"] = int(kind_bucket["picks_total"]) + slip_read.picks_total
        kind_bucket["picks_won"] = int(kind_bucket["picks_won"]) + slip_read.picks_won
        kind_bucket["picks_lost"] = int(kind_bucket["picks_lost"]) + slip_read.picks_lost
        kind_bucket["picks_pending"] = int(kind_bucket["picks_pending"]) + slip_read.picks_pending
        kind_bucket["picks_void"] = int(kind_bucket["picks_void"]) + slip_read.picks_void
        if slip_read.slip_status == "won":
            kind_bucket["slips_won"] = int(kind_bucket["slips_won"]) + 1
        elif slip_read.slip_status == "lost":
            kind_bucket["slips_lost"] = int(kind_bucket["slips_lost"]) + 1
        elif slip_read.slip_status == "void":
            kind_bucket["slips_void"] = int(kind_bucket["slips_void"]) + 1
        else:
            kind_bucket["slips_pending"] = int(kind_bucket["slips_pending"]) + 1
        if slip_read.slip_status in {"won", "lost"}:
            kind_bucket["profit_units"] = float(kind_bucket["profit_units"]) + _slip_profit_units(
                slip_read, stake
            )
            kind_bucket["resolved_count"] = int(kind_bucket["resolved_count"]) + 1

        profile = profile_stats[slip.slip_key]
        profile["label"] = slip.label
        profile["slip_kind"] = kind
        profile["strategy_family"] = _slip_strategy_family(slip)
        profile["strategy_version"] = _slip_strategy_version(slip)
        profile["is_experimental"] = bool(getattr(slip, "is_experimental", False))
        profile["slips_total"] = int(profile["slips_total"]) + 1
        if slip_read.slip_status == "won":
            profile["slips_won"] = int(profile["slips_won"]) + 1
        elif slip_read.slip_status == "lost":
            profile["slips_lost"] = int(profile["slips_lost"]) + 1
        elif slip_read.slip_status == "void":
            profile["slips_void"] = int(profile["slips_void"]) + 1
        else:
            profile["slips_pending"] = int(profile["slips_pending"]) + 1
        if slip_read.slip_status in {"won", "lost"}:
            profile["profit_units"] = float(profile["profit_units"]) + _slip_profit_units(
                slip_read, stake
            )
            profile["resolved_count"] = int(profile["resolved_count"]) + 1

        strategy_key = (_slip_strategy_family(slip), kind)
        strategy_profit = _record_strategy_stats(
            strategy_stats[strategy_key],
            slip_read=slip_read,
            strategy_version=_slip_strategy_version(slip),
            is_experimental=bool(getattr(slip, "is_experimental", False)),
            stake=stake,
        )
        if strategy_profit is not None:
            strategy_daily_profits[strategy_key][slip.slip_date].append(strategy_profit)
        elif slip_read.slip_status == "pending":
            strategy_pending_days[strategy_key].add(slip.slip_date)

    by_kind = [
        BettingSlipStatsKind(
            slip_kind=kind,
            label=slip_kind_label(kind),
            slips_total=int(stats["slips_total"]),
            slips_won=int(stats["slips_won"]),
            slips_lost=int(stats["slips_lost"]),
            slips_pending=int(stats["slips_pending"]),
            slips_void=int(stats["slips_void"]),
            slip_win_rate_pct=_pct(
                int(stats["slips_won"]),
                int(stats["slips_won"]) + int(stats["slips_lost"]),
            ),
            picks_total=int(stats["picks_total"]),
            picks_won=int(stats["picks_won"]),
            picks_lost=int(stats["picks_lost"]),
            picks_pending=int(stats["picks_pending"]),
            picks_void=int(stats["picks_void"]),
            pick_hit_rate_pct=_pct(
                int(stats["picks_won"]),
                int(stats["picks_won"]) + int(stats["picks_lost"]),
            ),
            theoretical_profit_units=round(float(stats["profit_units"]), 2),
            theoretical_roi_pct=(
                round(
                    (float(stats["profit_units"]) / (stake * int(stats["resolved_count"])))
                    * 100,
                    1,
                )
                if int(stats["resolved_count"]) and stake
                else None
            ),
        )
        for kind, stats in kind_stats.items()
        if int(stats["slips_total"]) > 0
    ]
    by_profile = [
        BettingSlipStatsProfile(
            slip_key=slip_key,
            label=str(stats["label"] or slip_key),
            slip_kind="ladder" if stats.get("slip_kind") == "ladder" else "parlay",
            strategy_family=str(stats["strategy_family"]),
            strategy_version=str(stats["strategy_version"]),
            is_experimental=bool(stats["is_experimental"]),
            slips_won=int(stats["slips_won"]),
            slips_lost=int(stats["slips_lost"]),
            slips_pending=int(stats["slips_pending"]),
            slips_void=int(stats["slips_void"]),
            slips_total=int(stats["slips_total"]),
            slip_win_rate_pct=_pct(
                int(stats["slips_won"]),
                int(stats["slips_won"]) + int(stats["slips_lost"]),
            ),
            theoretical_profit_units=round(float(stats["profit_units"]), 2),
            theoretical_roi_pct=(
                round(
                    float(stats["profit_units"])
                    / (stake * int(stats["resolved_count"]))
                    * 100,
                    1,
                )
                if int(stats["resolved_count"]) and stake
                else None
            ),
        )
        for slip_key, stats in sorted(
            profile_stats.items(),
            key=lambda item: (
                item[1].get("slip_kind") != "ladder",
                str(item[1].get("label") or item[0]),
            ),
        )
    ]
    by_strategy = _build_strategy_stats_rows(
        strategy_stats,
        strategy_daily_profits,
        strategy_pending_days,
        stake=stake,
    )
    return by_kind, by_profile, by_strategy


def _aggregate_slip_picks_by_market(
    db: Session,
    *,
    from_date: date,
    to_date: date,
    stake: float,
) -> list[BettingSlipMarketStatsRow]:
    slips = list(
        db.scalars(
            select(BettingSlip)
            .options(selectinload(BettingSlip.picks))
            .where(
                BettingSlip.slip_date >= from_date,
                BettingSlip.slip_date <= to_date,
            )
            .order_by(BettingSlip.slip_date.asc(), BettingSlip.id.asc())
        ).all()
    )
    if not slips:
        return []

    event_keys = [pick.event_key for slip in slips for pick in slip.picks]
    predictions: dict[int, MatchPrediction] = {}
    fixtures: dict[int, Fixture] = {}
    next_fixtures: dict[int, NextFixture] = {}
    for model_version, model_name in {
        (slip.model_version, slip.model_name) for slip in slips
    }:
        model_predictions, model_fixtures, model_next_fixtures = _load_outcome_context(
            db,
            event_keys,
            model_version,  # type: ignore[arg-type]
            model_name,
        )
        predictions.update(model_predictions)
        fixtures.update(model_fixtures)
        next_fixtures.update(model_next_fixtures)

    tallies: dict[str, dict[str, int]] = {}
    for slip in slips:
        slip_read = _slip_read(
            slip,
            predictions=predictions,
            fixtures=fixtures,
            next_fixtures=next_fixtures,
            stake=stake,
        )
        for pick in slip_read.picks:
            market = pick.market or "match_winner"
            bucket = tallies.setdefault(
                market,
                {
                    "picks_total": 0,
                    "picks_won": 0,
                    "picks_lost": 0,
                    "picks_pending": 0,
                    "picks_void": 0,
                },
            )
            bucket["picks_total"] += 1
            if pick.pick_status == "won":
                bucket["picks_won"] += 1
            elif pick.pick_status == "lost":
                bucket["picks_lost"] += 1
            elif pick.pick_status == "void":
                bucket["picks_void"] += 1
            else:
                bucket["picks_pending"] += 1

    market_order = ("match_winner", "first_set_winner", "over_under_games")
    rows: list[BettingSlipMarketStatsRow] = []
    for market in market_order:
        if market not in tallies:
            continue
        bucket = tallies[market]
        resolved = bucket["picks_won"] + bucket["picks_lost"]
        rows.append(
            BettingSlipMarketStatsRow(
                market=market,
                picks_total=bucket["picks_total"],
                picks_won=bucket["picks_won"],
                picks_lost=bucket["picks_lost"],
                picks_pending=bucket["picks_pending"],
                picks_void=bucket["picks_void"],
                pick_hit_rate_pct=_pct(bucket["picks_won"], resolved),
            )
        )
    for market, bucket in sorted(tallies.items()):
        if market in market_order:
            continue
        resolved = bucket["picks_won"] + bucket["picks_lost"]
        rows.append(
            BettingSlipMarketStatsRow(
                market=market,
                picks_total=bucket["picks_total"],
                picks_won=bucket["picks_won"],
                picks_lost=bucket["picks_lost"],
                picks_pending=bucket["picks_pending"],
                picks_void=bucket["picks_void"],
                pick_hit_rate_pct=_pct(bucket["picks_won"], resolved),
            )
        )
    return rows


class BettingSlipImageExportError(ValueError):
    """Raised when a betting-slip image export cannot be produced."""


def _slip_payload_for_image(slip: BettingSlipRead) -> dict:
    return slip.model_dump(mode="json")


def render_daily_betting_slip_png(
    db: Session,
    *,
    slip_key: str,
    slip_date: date | None = None,
    model_version: ModelVersion = DEFAULT_ACTIVE_MATCH_WINNER_VERSION,
    model_name: str | None = None,
    stake: float = DEFAULT_STAKE,
    min_edge_percent: float | None = None,
) -> tuple[bytes, str]:
    """Render a single daily slip as PNG (same layout as Telegram)."""
    from backend.src.app.telegram.images import BettingSlipImageError, render_betting_slip_png

    daily = get_daily_betting_slips(
        db=db,
        slip_date=slip_date,
        model_version=model_version,
        model_name=model_name,
        stake=stake,
        min_edge_percent=min_edge_percent,
        regenerate=False,
    )
    slip = next((item for item in daily.slips if item.slip_key == slip_key), None)
    if slip is None:
        raise BettingSlipImageExportError(f"Schedina '{slip_key}' non trovata per la data selezionata.")
    try:
        image = render_betting_slip_png(
            _slip_payload_for_image(slip),
            slip_date=daily.date.isoformat(),
            stake=daily.stake,
            min_edge_percent=min_edge_percent if min_edge_percent is not None else 2.0,
        )
    except BettingSlipImageError as exc:
        raise BettingSlipImageExportError(str(exc)) from exc
    filename = getattr(image, "name", None) or f"{slip_key}.png"
    return image.getvalue(), filename


def render_daily_betting_slip_images_zip(
    db: Session,
    *,
    slip_date: date | None = None,
    model_version: ModelVersion = DEFAULT_ACTIVE_MATCH_WINNER_VERSION,
    model_name: str | None = None,
    stake: float = DEFAULT_STAKE,
    min_edge_percent: float | None = None,
) -> tuple[bytes, str]:
    """Render all daily slips as a ZIP of PNG files (same layout as Telegram)."""
    import zipfile

    from backend.src.app.telegram.images import BettingSlipImageError, render_betting_slip_png

    daily = get_daily_betting_slips(
        db=db,
        slip_date=slip_date,
        model_version=model_version,
        model_name=model_name,
        stake=stake,
        min_edge_percent=min_edge_percent,
        regenerate=False,
    )
    if not daily.slips:
        raise BettingSlipImageExportError("Nessuna schedina disponibile da esportare.")

    buffer = BytesIO()
    used_names: set[str] = set()
    try:
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, slip in enumerate(daily.slips, start=1):
                image = render_betting_slip_png(
                    _slip_payload_for_image(slip),
                    slip_date=daily.date.isoformat(),
                    stake=daily.stake,
                    min_edge_percent=min_edge_percent if min_edge_percent is not None else 2.0,
                )
                name = getattr(image, "name", None) or f"{slip.slip_key}.png"
                if name in used_names:
                    stem = name[:-4] if name.lower().endswith(".png") else name
                    name = f"{stem}_{index}.png"
                used_names.add(name)
                archive.writestr(name, image.getvalue())
    except BettingSlipImageError as exc:
        raise BettingSlipImageExportError(str(exc)) from exc

    date_label = daily.date.isoformat()
    filename = f"schedine_{date_label}_{daily.model_version}_{daily.model_name}.zip"
    return buffer.getvalue(), filename
