from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

GlobalUpdateStatus = Literal[
    "pending",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
    "interrupted",
]
GlobalUpdateOrigin = Literal["manual", "cron", "job"]
GlobalUpdateItemStatus = Literal["pending", "running", "completed", "failed", "skipped", "cancelled"]


class GlobalUpdateStartRequest(BaseModel):
    force: bool = False
    force_outside_hours: bool = False
    days_forward: int = Field(default=10, ge=1, le=30)
    days_back_fixtures: int = Field(default=3, ge=0, le=30)
    resume: bool = False
    resume_run_id: int | None = None
    sync_cloud: bool = False
    versions: list[str] | None = None


class GlobalUpdateStartResponse(BaseModel):
    run_id: int
    status: GlobalUpdateStatus
    message: str


class GlobalUpdateRunItemRead(BaseModel):
    model_version: str
    model_name: str
    status: GlobalUpdateItemStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    predictions_generated: int = 0
    slips_generated: int = 0
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)


class GlobalUpdateRunRead(BaseModel):
    id: int
    run_date: date
    origin: GlobalUpdateOrigin
    status: GlobalUpdateStatus
    current_phase: str | None = None
    progress_pct: float | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    force: bool = False
    versions_processed: int = 0
    models_processed: int = 0
    combinations_completed: int = 0
    combinations_failed: int = 0
    combinations_skipped: int = 0
    fixtures_processed: int = 0
    slips_generated: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    items: list[GlobalUpdateRunItemRead] = Field(default_factory=list)


class GlobalUpdateReportRead(BaseModel):
    run_id: int
    run_date: date
    origin: GlobalUpdateOrigin
    status: GlobalUpdateStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    phases: list[dict[str, Any]] = Field(default_factory=list)
    items: list[GlobalUpdateRunItemRead] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ModelVersionResultModel(BaseModel):
    model: str
    status: GlobalUpdateItemStatus | str
    predictions_count: int = 0
    slips_count: int = 0
    data: dict[str, Any] = Field(default_factory=dict)


class ModelVersionResultVersion(BaseModel):
    version: str
    models: list[ModelVersionResultModel] = Field(default_factory=list)


class ModelsVersionsResultsResponse(BaseModel):
    date: date
    last_updated_at: datetime | None = None
    last_run_id: int | None = None
    last_run_origin: GlobalUpdateOrigin | None = None
    versions: list[ModelVersionResultVersion] = Field(default_factory=list)
