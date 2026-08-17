"""Pydantic schemas for segment ROI analysis (ML-04)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

AnalysisSource = Literal["live", "walk_forward", "backtest"]
SegmentDimension = Literal[
    "surface",
    "tournament",
    "circuit",
    "level",
    "round",
    "favorite_role",
    "odds_band",
    "bookmaker",
    "model",
    "version",
    "period",
]


class SegmentRoiBucketRead(BaseModel):
    key: str
    label: str
    predictions_total: int
    closed: int
    void: int
    open: int
    won: int
    lost: int
    hit_rate_pct: float | None = None
    avg_odds: float | None = None
    avg_edge_pct: float | None = None
    stake_total: float
    stake_settled: float
    profit: float
    roi_pct: float | None = None
    yield_pct: float | None = None
    max_drawdown: float
    hit_rate_ci_lower_pct: float | None = None
    hit_rate_ci_upper_pct: float | None = None
    roi_ci_lower_pct: float | None = None
    roi_ci_upper_pct: float | None = None
    insufficient_sample: bool


class SegmentRoiGroupRead(BaseModel):
    fold_index: int | None = None
    period: str | None = None
    predictions_total: int
    closed: int
    void: int
    open: int
    won: int
    lost: int
    segments: list[SegmentRoiBucketRead]


class SegmentRoiAnalysisRead(BaseModel):
    source: AnalysisSource
    segment_dimension: SegmentDimension
    min_segment_samples: int
    model_version: str | None = None
    model_name: str | None = None
    market: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    event_date_from: date | None = None
    event_date_to: date | None = None
    predictions_total: int
    closed: int
    void: int
    open: int
    won: int
    lost: int
    segments: list[SegmentRoiBucketRead]
    by_fold: list[SegmentRoiGroupRead] = Field(default_factory=list)
    by_period: list[SegmentRoiGroupRead] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
