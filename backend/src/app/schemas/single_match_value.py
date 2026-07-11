from datetime import date, time
from typing import Literal

from pydantic import BaseModel


SingleMatchValueDecision = Literal["PLAY", "NO BET", "BORDERLINE"]


class SingleMatchValueItem(BaseModel):
    match_id: int
    event_date: date | None = None
    event_time: time | None = None
    tournament_name: str | None = None
    competition: str | None = None
    player_a: str | None = None
    player_b: str | None = None
    market: str
    selection: str
    selection_code: str
    model_probability: float
    market_odds: float
    void_odds: float
    edge_absolute: float
    edge_percent: float
    expected_roi: float
    stake: float = 1.0
    decision: SingleMatchValueDecision
    value_label: str
    edge_label: str
    explanation: str
    bookmaker_count: int | None = None
    actual_winner: str | None = None
    is_correct: bool | None = None
    profit_loss: float | None = None


class SingleMatchValueSimulationBucket(BaseModel):
    bets_count: int
    resolved_count: int
    profit_loss_units: float
    roi_pct: float | None = None
    hit_rate_pct: float | None = None
    avg_market_odds: float | None = None
    avg_void_odds: float | None = None


class SingleMatchValueSimulation(BaseModel):
    stake: float
    play_bets: SingleMatchValueSimulationBucket
    above_void: SingleMatchValueSimulationBucket
    below_void: SingleMatchValueSimulationBucket
    borderline_count: int


class SingleMatchValueSummary(BaseModel):
    total: int
    play_count: int
    no_bet_count: int
    borderline_count: int
    avg_market_odds: float | None = None
    avg_void_odds: float | None = None
    avg_expected_roi: float | None = None


class SingleMatchValueResponse(BaseModel):
    model_version: str
    model_name: str | None = None
    min_edge_percent: float
    items: list[SingleMatchValueItem]
    total: int
    offset: int
    limit: int
    summary: SingleMatchValueSummary
    simulation: SingleMatchValueSimulation
    warnings: list[str] = []
