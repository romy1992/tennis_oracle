from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PickStatus = Literal["pending", "won", "lost"]
SlipStatus = Literal["pending", "won", "lost"]


class BettingSlipPickRead(BaseModel):
    event_key: int
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
    confidence: float | None = None
    pick_score: float | None = None
    pick_status: PickStatus = "pending"
    actual_winner_label: str | None = None
    is_correct: bool | None = None


class BettingSlipRead(BaseModel):
    id: str
    slip_key: str
    label: str
    description: str | None = None
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
    picks_total: int = 0
    resolved_combined_odds: float | None = None
    theoretical_profit_if_won: float | None = None
    generated_at: datetime | None = None


class BettingSlipsDailyResponse(BaseModel):
    date: date
    model_version: str
    model_name: str
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
    picks_total: int
    picks_won: int
    picks_lost: int
    picks_pending: int
    slip_win_rate_pct: float | None = None
    pick_hit_rate_pct: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None


class BettingSlipStatsProfile(BaseModel):
    slip_key: str
    label: str
    slips_won: int
    slips_lost: int
    slips_pending: int = 0
    slips_total: int = 0
    slip_win_rate_pct: float | None = None


class BettingSlipStatsSummary(BaseModel):
    slips_total: int
    slips_won: int
    slips_lost: int
    slips_pending: int
    picks_total: int
    picks_won: int
    picks_lost: int
    picks_pending: int
    slip_win_rate_pct: float | None = None
    pick_hit_rate_pct: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None
    by_profile: list[BettingSlipStatsProfile] = Field(default_factory=list)


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
    slip_win_rate_pct: float | None = None
    picks_total: int
    picks_won: int
    picks_lost: int
    picks_pending: int
    pick_hit_rate_pct: float | None = None
    theoretical_profit_units: float = 0.0
    theoretical_roi_pct: float | None = None
    first_date: date
    last_date: date


class BettingSlipModelStatsResponse(BaseModel):
    from_date: date
    to_date: date
    stake: float
    rows: list[BettingSlipModelStatsRow] = Field(default_factory=list)
