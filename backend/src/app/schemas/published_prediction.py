"""Pydantic schemas for the immutable published-prediction ledger."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PublicationSource = Literal[
    "admin_api",
    "telegram",
    "global_update",
    "system",
    "manual",
]

InitialStatus = Literal["published", "draft"]
PredictionMarket = Literal["match_winner", "first_set_winner", "over_under_games"]
ValueDecision = Literal["PLAY", "BORDERLINE", "NO BET"]


class PublishedPredictionCreate(BaseModel):
    event_key: int
    market: PredictionMarket = "match_winner"
    value_decision: ValueDecision | None = None
    official_play: bool = False
    selection: str = Field(min_length=1, max_length=255)
    model_version: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=128)
    probability: float = Field(gt=0.0, lt=1.0)
    odds: float | None = Field(default=None, gt=1.0)
    void_odds: float | None = Field(default=None, gt=1.0)
    edge: float | None = None
    unit_stake: float = Field(default=1.0, gt=0.0)
    publication_source: PublicationSource = "admin_api"
    initial_status: InitialStatus = "published"
    player_1_name: str | None = None
    player_2_name: str | None = None
    tournament_name: str | None = None
    event_date: date | None = None
    event_time: time | None = None
    match_prediction_id: int | None = None
    betting_slip_pick_id: int | None = None


class PublishedPredictionCorrection(BaseModel):
    """Payload for a new immutable version linked to a previous publication."""

    market: PredictionMarket | None = None
    value_decision: ValueDecision | None = None
    official_play: bool = False
    selection: str | None = Field(default=None, min_length=1, max_length=255)
    model_version: str | None = Field(default=None, min_length=1, max_length=64)
    model_name: str | None = Field(default=None, min_length=1, max_length=128)
    probability: float | None = Field(default=None, gt=0.0, lt=1.0)
    odds: float | None = Field(default=None, gt=1.0)
    void_odds: float | None = Field(default=None, gt=1.0)
    edge: float | None = None
    unit_stake: float | None = Field(default=None, gt=0.0)
    publication_source: PublicationSource = "admin_api"
    initial_status: InitialStatus = "published"
    player_1_name: str | None = None
    player_2_name: str | None = None
    tournament_name: str | None = None
    event_date: date | None = None
    event_time: time | None = None
    match_prediction_id: int | None = None
    betting_slip_pick_id: int | None = None


class PublishedPredictionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    publication_id: str
    content_version: int
    previous_version_id: int | None = None
    event_key: int
    market: PredictionMarket = "match_winner"
    value_decision: ValueDecision | None = None
    official_play: bool = False
    selection: str
    model_version: str
    model_name: str
    probability: float
    odds: float | None = None
    void_odds: float | None = None
    edge: float | None = None
    publication_odds: float | None = None
    publication_bookmaker: str | None = None
    closing_odds: float | None = None
    closing_bookmaker: str | None = None
    no_vig_publication_prob: float | None = None
    no_vig_closing_prob: float | None = None
    clv_pct: float | None = None
    clv_prob_delta_pct: float | None = None
    clv_available: bool = False
    # How closing_odds was obtained: "same_bookmaker" (publication snapshot of a
    # real bookmaker) or "consensus_avg" (mean of the bookmakers' quotes in the
    # last valid pre-kickoff closing capture, for average published odds).
    closing_basis: str | None = None
    closing_bookmaker_count: int | None = None
    closing_captured_at: datetime | None = None
    # (odds * no_vig_closing_prob - 1) * 100: return of the taken price at the
    # closing fair probability.
    clv_no_vig_pct: float | None = None
    # Why clv_pct is missing: no_published_odds | awaiting_closing |
    # closing_after_kickoff | closing_before_publication |
    # selection_not_in_closing | no_closing_snapshot.
    clv_missing_reason: str | None = None
    unit_stake: float
    published_at: datetime
    publication_source: str
    initial_status: str
    content_hash: str
    player_1_name: str | None = None
    player_2_name: str | None = None
    tournament_name: str | None = None
    event_date: date | None = None
    event_time: time | None = None
    match_prediction_id: int | None = None
    betting_slip_pick_id: int | None = None
    is_latest: bool = False
    match_started: bool = False


class PublishedPredictionListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PublishedPredictionRead]


class PublishedPredictionVersionChainResponse(BaseModel):
    publication_id: str
    items: list[PublishedPredictionRead]


class PublishedLiveStatsBucket(BaseModel):
    """Aggregate KPIs for one distribution bucket (model / odds / edge / surface / period)."""

    key: str
    label: str
    predictions_total: int
    closed: int
    open: int
    void: int
    won: int
    lost: int
    hit_rate_pct: float | None = None
    stake_total: float
    stake_settled: float
    profit: float
    roi_pct: float | None = None
    yield_pct: float | None = None
    avg_odds: float | None = None
    clv_count: int = 0
    clv_missing: int = 0
    clv_coverage_pct: float | None = None
    clv_avg_pct: float | None = None
    clv_median_pct: float | None = None
    clv_positive_pct: float | None = None
    clv_avg_prob_delta_pct: float | None = None


OddsBand = Literal["lt_1_50", "1_50_2_00", "2_00_3_00", "gte_3_00", "missing"]


class PublishedSettledTipRead(PublishedPredictionRead):
    """Published tip with read-time settlement for live beta views."""

    outcome: Literal["pending", "won", "lost", "void"]
    profit: float
    stake_settled: float
    surface: str | None = None


class PublishedLiveStatsSummary(BaseModel):
    """Live tipbook KPIs derived only from the immutable published ledger."""

    source: Literal["published_prediction"] = "published_prediction"
    latest_only: bool
    from_date: date | None = None
    to_date: date | None = None
    event_date_from: date | None = None
    event_date_to: date | None = None
    model_version: str | None = None
    model_name: str | None = None
    publication_source: str | None = None
    tournament_name: str | None = None
    surface: str | None = None
    odds_band: OddsBand | None = None
    market: PredictionMarket | None = None
    include_archived: bool = True
    official_only: bool = False

    predictions_total: int
    closed: int
    open: int
    void: int
    won: int
    lost: int
    hit_rate_pct: float | None = None
    stake_total: float
    stake_settled: float
    profit: float
    roi_pct: float | None = None
    yield_pct: float | None = None
    avg_odds: float | None = None
    max_drawdown: float
    max_winning_streak: int
    max_losing_streak: int
    clv_count: int = 0
    clv_missing: int = 0
    clv_coverage_pct: float | None = None
    clv_avg_pct: float | None = None
    clv_median_pct: float | None = None
    clv_positive_pct: float | None = None
    clv_avg_prob_delta_pct: float | None = None

    by_model: list[PublishedLiveStatsBucket]
    by_odds: list[PublishedLiveStatsBucket]
    by_edge: list[PublishedLiveStatsBucket]
    by_surface: list[PublishedLiveStatsBucket]
    by_period: list[PublishedLiveStatsBucket]


class PublishedClvBucket(BaseModel):
    """CLV of one group of published tips (market / decision / market×decision)."""

    key: str
    label: str
    predictions_total: int
    clv_count: int = 0
    clv_missing: int = 0
    clv_coverage_pct: float | None = None
    # Tips whose CLV can already be expected: excludes those still awaiting the
    # pre-kickoff closing window and those published without odds.
    clv_eligible: int = 0
    clv_coverage_eligible_pct: float | None = None
    clv_avg_pct: float | None = None
    clv_median_pct: float | None = None
    clv_positive_count: int = 0
    clv_positive_pct: float | None = None
    clv_no_vig_count: int = 0
    clv_no_vig_avg_pct: float | None = None
    clv_no_vig_median_pct: float | None = None
    clv_no_vig_positive_pct: float | None = None
    closing_basis_counts: dict[str, int] = Field(default_factory=dict)
    missing_reasons: dict[str, int] = Field(default_factory=dict)


class PublishedClvSummary(BaseModel):
    """Read-only CLV report of the published ledger, by market and by decision."""

    source: Literal["published_prediction"] = "published_prediction"
    clv_formula: str
    clv_no_vig_formula: str
    closing_rules: list[str]
    latest_only: bool
    from_date: date | None = None
    to_date: date | None = None
    event_date_from: date | None = None
    event_date_to: date | None = None
    model_version: str | None = None
    model_name: str | None = None
    publication_source: str | None = None
    market: PredictionMarket | None = None
    include_archived: bool = True
    official_only: bool = False

    overall: PublishedClvBucket
    by_market: list[PublishedClvBucket]
    by_decision: list[PublishedClvBucket]
    by_market_decision: list[PublishedClvBucket]
