"""Pydantic schemas for probability / edge band analysis (ML-03)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from backend.src.app.ml.training.calibration import CalibrationMethod

AnalysisSource = Literal["live", "walk_forward", "backtest"]
BandDimension = Literal["probability", "edge"]


class ProbabilityBandBucketRead(BaseModel):
    key: str
    label: str
    bin_start: float | None = None
    bin_end: float | None = None
    predictions_total: int
    closed: int
    void: int
    open: int
    won: int
    lost: int
    hit_rate_pct: float | None = None
    mean_predicted_pct: float | None = None
    mean_observed_pct: float | None = None
    calibration_gap_pct: float | None = None
    avg_odds: float | None = None
    avg_edge_pct: float | None = None
    stake_total: float
    stake_settled: float
    profit: float
    roi_pct: float | None = None
    yield_pct: float | None = None
    hit_rate_ci_lower_pct: float | None = None
    hit_rate_ci_upper_pct: float | None = None
    insufficient_sample: bool


class ProbabilityBandGroupRead(BaseModel):
    fold_index: int | None = None
    period: str | None = None
    predictions_total: int
    closed: int
    void: int
    open: int
    won: int
    lost: int
    bands: list[ProbabilityBandBucketRead]


class ProbabilityBandAnalysisRead(BaseModel):
    source: AnalysisSource
    band_dimension: BandDimension
    probability_kind: CalibrationMethod
    n_bins: int
    min_bin_samples: int
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
    bands: list[ProbabilityBandBucketRead]
    comparison: dict[str, list[ProbabilityBandBucketRead]] = Field(default_factory=dict)
    by_fold: list[ProbabilityBandGroupRead] = Field(default_factory=list)
    by_period: list[ProbabilityBandGroupRead] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
