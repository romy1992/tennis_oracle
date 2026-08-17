"""Schemas for walk-forward validation API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


WalkForwardMode = Literal["expanding", "rolling"]
WalkForwardRunStatus = Literal[
    "pending",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
]
WalkForwardFoldStatus = Literal[
    "completed",
    "skipped_insufficient_data",
    "skipped_single_class",
    "error",
]


class WalkForwardConfigSchema(BaseModel):
    mode: WalkForwardMode = "expanding"
    initial_train_days: int = Field(default=365, ge=1)
    test_days: int = Field(default=90, ge=1)
    step_days: int = Field(default=90, ge=1)
    min_train_rows: int = Field(default=200, ge=2)
    min_test_rows: int = Field(default=50, ge=1)
    embargo_days: int = Field(default=0, ge=0)
    edge_threshold: float = Field(default=0.03, ge=0.0)
    random_state: int = 42
    # Match-winner tags (v1-v4) or extra-market labels (e.g. first_set_winner_v2,
    # over_under_games_v1, see walk_forward_markets.ALL_WALK_FORWARD_VERSIONS).
    # Left as free-form str: this schema module must not import the ML layer.
    versions: list[str] | None = None


class WalkForwardFoldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    fold_index: int
    model_version: str
    model_name: str
    dataset_path: str
    status: WalkForwardFoldStatus | str
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    train_rows: int
    test_rows: int
    feature_set: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] | None = None
    market_benchmark: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None
    leakage_flags: list[str] = Field(default_factory=list)
    skip_reason: str | None = None


class WalkForwardRunListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: WalkForwardRunStatus | str
    mode: WalkForwardMode | str
    initial_train_days: int
    test_days: int
    step_days: int
    versions_requested: str
    origin: str
    current_phase: str | None = None
    progress_pct: float | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    cancel_requested: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    created_at: datetime
    created_by: str
    folds_completed: int = 0
    folds_skipped: int = 0
    folds_errors: int = 0
    leakage_flags_total: int = 0


class WalkForwardRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: WalkForwardRunStatus | str
    mode: WalkForwardMode | str
    initial_train_days: int
    test_days: int
    step_days: int
    min_train_rows: int
    min_test_rows: int
    embargo_days: int
    edge_threshold: float
    random_state: int
    versions_requested: str
    origin: str
    current_phase: str | None = None
    progress_pct: float | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    cancel_requested: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    report_path: str | None = None
    summary: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    created_by: str
    folds: list[WalkForwardFoldRead] = Field(default_factory=list)


class WalkForwardRunListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[WalkForwardRunListItem]


class WalkForwardTriggerRequest(WalkForwardConfigSchema):
    """Optional overrides; defaults come from Settings / engine defaults."""

    blocking: bool = False


class WalkForwardTriggerResponse(BaseModel):
    run: WalkForwardRunRead
    started: bool
    message: str


class WalkForwardCancelResponse(BaseModel):
    run_id: int
    status: WalkForwardRunStatus | str
    message: str


class WalkForwardGlobalUpdateSummary(BaseModel):
    """Lightweight observability payload embedded in global-update reports."""

    available: bool = False
    latest_run_id: int | None = None
    status: str | None = None
    mode: str | None = None
    finished_at: datetime | None = None
    folds_completed: int | None = None
    folds_skipped: int | None = None
    folds_errors: int | None = None
    leakage_flags_total: int | None = None
    note: str = (
        "Walk-forward è separato dalla validazione live e non aggiorna il modello pubblico."
    )
