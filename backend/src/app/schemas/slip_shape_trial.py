"""Read model for the frozen slip-shape trial page."""

from datetime import date

from pydantic import BaseModel


class SlipSliceRead(BaseModel):
    label: str
    slips_won: int
    slips_lost: int
    slips_pending: int
    slip_win_rate_pct: float | None = None
    picks_won: int
    picks_lost: int
    pick_hit_rate_pct: float | None = None
    profit_units: float
    stake_units: float
    roi_pct: float | None = None


class SingleSliceRead(BaseModel):
    label: str
    won: int
    lost: int
    pending: int
    hit_rate_pct: float | None = None
    profit_units: float
    stake_units: float
    roi_pct: float | None = None


class SelectionCheckRead(BaseModel):
    method: str
    dimension: str
    band: str
    august_settled: int
    august_roi_pct: float | None = None
    september_settled: int
    september_roi_pct: float | None = None
    passed: bool


class ForwardTrialRead(BaseModel):
    window_from: date
    window_to: date
    ready: bool
    settled_slips: int
    slips_needed: int
    rule: str
    note: str
    short_slips: SlipSliceRead


class SlipShapeTrialRead(BaseModel):
    window_from: date
    window_to: date
    split_date: date
    model_version: str
    model_name: str
    stake: float
    min_samples: int
    selection_passed: bool
    passing_rules: list[str]
    conclusion: str
    short_slip_rule: str
    official_slips: SlipSliceRead
    short_slips: SlipSliceRead
    match_winner_singles: SingleSliceRead
    first_set_singles: SingleSliceRead
    over_under_singles: SingleSliceRead
    checks: list[SelectionCheckRead]
    forward: ForwardTrialRead
