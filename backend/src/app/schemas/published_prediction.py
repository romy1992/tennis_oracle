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


class PublishedPredictionCreate(BaseModel):
    event_key: int
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
    selection: str
    model_version: str
    model_name: str
    probability: float
    odds: float | None = None
    void_odds: float | None = None
    edge: float | None = None
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

    by_model: list[PublishedLiveStatsBucket]
    by_odds: list[PublishedLiveStatsBucket]
    by_edge: list[PublishedLiveStatsBucket]
    by_surface: list[PublishedLiveStatsBucket]
    by_period: list[PublishedLiveStatsBucket]
