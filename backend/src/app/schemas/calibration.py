"""Schemas for probability calibration API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CalibrationMethod = Literal["raw", "platt", "isotonic"]
CalibrationRunStatus = Literal[
    "pending",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
]


class CalibrationConfigSchema(BaseModel):
    n_bins: int = Field(default=10, ge=2)
    min_bin_samples: int = Field(default=30, ge=1)
    min_calibrator_train_samples: int = Field(default=100, ge=2)
    methods: list[CalibrationMethod] | None = None
    # Walk-forward window overrides (defaults from Settings)
    mode: Literal["expanding", "rolling"] | None = None
    initial_train_days: int | None = Field(default=None, ge=1)
    test_days: int | None = Field(default=None, ge=1)
    step_days: int | None = Field(default=None, ge=1)
    min_train_rows: int | None = Field(default=None, ge=2)
    min_test_rows: int | None = Field(default=None, ge=1)
    embargo_days: int | None = Field(default=None, ge=0)
    edge_threshold: float | None = Field(default=None, ge=0.0)
    random_state: int | None = None
    # Match-winner tags or extra-market labels. Runtime validation uses the
    # shared active walk-forward market registry without importing ML here.
    versions: list[str] | None = None
    walk_forward_run_id: int | None = None


class CalibrationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    model_version: str
    model_name: str
    dataset_path: str
    date_min: str | None = None
    date_max: str | None = None
    oos_samples_total: int
    aggregate: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None
    fold_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    leakage_flags: list[str] = Field(default_factory=list)
    skip_reason: str | None = None


class CalibrationRunListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: CalibrationRunStatus | str
    wf_mode: str
    wf_initial_train_days: int
    wf_test_days: int
    wf_step_days: int
    methods_requested: str
    versions_requested: str
    walk_forward_run_id: int | None = None
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
    models_with_oos: int = 0
    oos_samples_total: int = 0
    leakage_flags_total: int = 0


class CalibrationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: CalibrationRunStatus | str
    walk_forward_run_id: int | None = None
    n_bins: int
    min_bin_samples: int
    min_calibrator_train_samples: int
    wf_mode: str
    wf_initial_train_days: int
    wf_test_days: int
    wf_step_days: int
    wf_min_train_rows: int
    wf_min_test_rows: int
    wf_embargo_days: int
    wf_edge_threshold: float
    wf_random_state: int
    methods_requested: str
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
    results: list[CalibrationResultRead] = Field(default_factory=list)


class CalibrationRunListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CalibrationRunListItem]


class CalibrationTriggerRequest(CalibrationConfigSchema):
    blocking: bool = False


class CalibrationTriggerResponse(BaseModel):
    run: CalibrationRunRead
    started: bool
    message: str


class CalibrationCancelResponse(BaseModel):
    run_id: int
    status: CalibrationRunStatus | str
    message: str
