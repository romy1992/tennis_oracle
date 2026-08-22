from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PickStatus = Literal["pending", "won", "lost", "void"]
SlipStatus = Literal["pending", "won", "lost", "void"]
SlipKind = Literal["parlay", "ladder"]
StrategyFamily = Literal["generic", "play_only", "strong_markets", "selective"]


class BettingSlipsGenerateRequest(BaseModel):
    """Optional body for regenerate flows with per-match margin overrides."""

    min_edge_overrides: dict[int, float] = Field(default_factory=dict)


class BettingSlipPickRead(BaseModel):
    event_key: int
    market: str = "match_winner"
    event_date: date | None = None
    event_time: time | None = None
    tournament_name: str | None = None
    surface: str | None = None
    player_1: str | None = None
    player_2: str | None = None
    predicted_winner: str
    predicted_winner_label: str | None = None
    model_prob: float | None = None
    market_prob: float | None = None
    edge: float | None = None
    odds: float | None = None
    void_odds: float | None = None
    edge_absolute: float | None = None
    edge_percent: float | None = None
    expected_roi: float | None = None
    suggested_min_edge_percent: float | None = None
    min_edge_percent: float | None = None
    value_decision: str | None = None
    value_label: str | None = None
    confidence: float | None = None
    pick_score: float | None = None
    pick_status: PickStatus = "pending"
    outcome: PickStatus = "pending"
    settled_at: datetime | None = None
    actual_winner_label: str | None = None
    is_correct: bool | None = None
    match_lifecycle_status: str | None = None
    match_lifecycle_label: str | None = None
    event_status: str | None = None
    live_score: dict | None = None
    void_reason: str | None = None
    # Populated for ladder slips: progressive stake at this step (base → reinvest).
    ladder_step_index: int | None = None
    ladder_step_stake: float | None = None
    ladder_step_return_if_won: float | None = None


class BettingSlipRead(BaseModel):
    id: str
    slip_key: str
    label: str
    description: str | None = None
    slip_kind: SlipKind = "parlay"
    strategy_family: StrategyFamily = "generic"
    strategy_version: str = "legacy_v1"
    is_experimental: bool = False
    picks: list[BettingSlipPickRead] = Field(default_factory=list)
    pick_count: int
    combined_odds: float
    combined_probability_estimate: float | None = None
    potential_return: float
    potential_profit: float
    slip_status: SlipStatus = "pending"
    picks_won: int = 0
    picks_lost: int = 0
    picks_pending: int = 0
    picks_void: int = 0
    picks_total: int = 0
    resolved_combined_odds: float | None = None
    effective_combined_odds: float | None = None
    theoretical_profit_if_won: float | None = None
    generated_at: datetime | None = None


class BettingSlipMarketModelRead(BaseModel):
    """Production model responsible for one market in the mixed slip pool."""

    market: str
    label: str
    model_version: str
    model_name: str


class BettingSlipsDailyResponse(BaseModel):
    date: date
    # Backward-compatible namespace fields. They select the Match Winner model;
    # the dedicated extra-market models are exposed explicitly in market_models.
    model_version: str
    model_name: str
    match_winner_model_version: str
    match_winner_model_name: str
    market_models: list[BettingSlipMarketModelRead] = Field(default_factory=list)
    stake: float
    candidate_pool_size: int
    slips: list[BettingSlipRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BettingSlipCalendarDay(BaseModel):
    date: date
    is_today: bool = False
    is_past: bool = False
    is_upcoming: bool = False
    has_slips: bool = False
    slip_count: int = 0
    fixture_count: int = 0
    candidate_pool_size: int | None = None


class BettingSlipCalendarResponse(BaseModel):
    today: date
    window_from: date
    window_to: date
    history_from: date | None = None
    model_version: str
    model_name: str
    days: list[BettingSlipCalendarDay] = Field(default_factory=list)


class BettingSlipRefreshSummary(BaseModel):
    fixtures_imported: bool = False
    predictions_resolved: int = 0
    slips_updated: int = 0
    next_fixtures_imported: bool = False
    import_status: dict | None = None


class BettingSlipsRefreshResponse(BettingSlipsDailyResponse):
    refresh_summary: BettingSlipRefreshSummary


class BettingSlipStatsDay(BaseModel):
    date: date
    slips_total: int
    slips_won: int
    slips_lost: int
    slips_pending: int
    slips_void: int = 0
    picks_total: int
    picks_won: int
    picks_lost: int
    picks_pending: int
    picks_void: int = 0
    slip_win_rate_pct: float | None = None
    pick_hit_rate_pct: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None


class BettingSlipStatsProfile(BaseModel):
    slip_key: str
    label: str
    slip_kind: SlipKind = "parlay"
    strategy_family: StrategyFamily = "generic"
    strategy_version: str = "legacy_v1"
    is_experimental: bool = False
    slips_won: int
    slips_lost: int
    slips_pending: int = 0
    slips_void: int = 0
    slips_total: int = 0
    slip_win_rate_pct: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None


class BettingSlipStatsStrategy(BaseModel):
    strategy_family: StrategyFamily
    label: str
    slip_kind: SlipKind
    strategy_versions: list[str] = Field(default_factory=list)
    is_experimental: bool = False
    slips_total: int
    slips_won: int
    slips_lost: int
    slips_pending: int = 0
    slips_void: int = 0
    slip_win_rate_pct: float | None = None
    picks_total: int = 0
    picks_won: int = 0
    picks_lost: int = 0
    picks_pending: int = 0
    picks_void: int = 0
    pick_hit_rate_pct: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None
    daily_portfolio_profit_units: float = 0.0
    daily_portfolio_roi_pct: float | None = None
    comparable_days: int = 0


class BettingSlipStatsKind(BaseModel):
    """Aggregate for parlays vs ladders in the same stats window."""

    slip_kind: SlipKind
    label: str
    slips_total: int
    slips_won: int
    slips_lost: int
    slips_pending: int = 0
    slips_void: int = 0
    slip_win_rate_pct: float | None = None
    picks_total: int = 0
    picks_won: int = 0
    picks_lost: int = 0
    picks_pending: int = 0
    picks_void: int = 0
    pick_hit_rate_pct: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None


class BettingSlipStatsSummary(BaseModel):
    slips_total: int
    slips_won: int
    slips_lost: int
    slips_pending: int
    slips_void: int = 0
    picks_total: int
    picks_won: int
    picks_lost: int
    picks_pending: int
    picks_void: int = 0
    slip_win_rate_pct: float | None = None
    pick_hit_rate_pct: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None
    by_profile: list[BettingSlipStatsProfile] = Field(default_factory=list)
    by_kind: list[BettingSlipStatsKind] = Field(default_factory=list)
    by_strategy: list[BettingSlipStatsStrategy] = Field(default_factory=list)


class BettingSlipStatsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_version: str
    from_date: date
    to_date: date
    days: list[BettingSlipStatsDay] = Field(default_factory=list)
    summary: BettingSlipStatsSummary


class BettingSlipModelStatsRow(BaseModel):
    model_version: str
    model_name: str
    slips_total: int
    slips_won: int
    slips_lost: int
    slips_pending: int
    slips_void: int = 0
    slip_win_rate_pct: float | None = None
    picks_total: int
    picks_won: int
    picks_lost: int
    picks_pending: int
    picks_void: int = 0
    pick_hit_rate_pct: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None
    first_date: date
    last_date: date


class BettingSlipMarketStatsRow(BaseModel):
    """Pick-level aggregate for one prediction market across slips in the window."""

    market: str
    picks_total: int
    picks_won: int
    picks_lost: int
    picks_pending: int
    picks_void: int = 0
    pick_hit_rate_pct: float | None = None


class BettingSlipModelStatsResponse(BaseModel):
    from_date: date
    to_date: date
    stake: float
    rows: list[BettingSlipModelStatsRow] = Field(default_factory=list)
    by_market: list[BettingSlipMarketStatsRow] = Field(default_factory=list)
    by_kind: list[BettingSlipStatsKind] = Field(default_factory=list)
    by_profile: list[BettingSlipStatsProfile] = Field(default_factory=list)
    by_strategy: list[BettingSlipStatsStrategy] = Field(default_factory=list)
