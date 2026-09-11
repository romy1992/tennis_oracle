"""Schemas for protected runtime provider settings."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

ScheduleKind = Literal["clock", "weekly_clock", "interval"]
ScheduleSource = Literal["database", "environment"]
ScheduledJobWorker = Literal["report_scheduler", "api_scheduler"]


class ApiTennisProviderSettingsRead(BaseModel):
    provider: Literal["api-tennis"] = "api-tennis"
    environment: str
    configured: bool
    usable: bool
    source: Literal["database", "environment", "missing"]
    fingerprint: str | None = None
    storage_ready: bool
    database_override_present: bool
    base_url: str | None = None
    timeout_seconds: float
    updated_at: datetime | None = None
    updated_by: str | None = None
    warning: str | None = None


class ApiTennisConnectionTestRequest(BaseModel):
    api_key: SecretStr | None = None


class ApiTennisConnectionTestResponse(BaseModel):
    ok: bool
    message: str


class ApiTennisKeyUpdateRequest(BaseModel):
    api_key: SecretStr
    admin_password: SecretStr
    verify_before_save: bool = True


class ApiTennisKeyUpdateResponse(BaseModel):
    message: str
    verified: bool
    settings: ApiTennisProviderSettingsRead


class ScheduledJobRead(BaseModel):
    job_key: str
    label: str
    description: str
    badge: str | None = None
    worker: ScheduledJobWorker
    schedule_kind: ScheduleKind
    enabled: bool
    clock_time: str | None = None
    weekday: int | None = None
    interval_seconds: int | None = None
    min_interval_seconds: int | None = None
    source: ScheduleSource
    last_run_at: datetime | None = None
    last_run_status: str | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


class ScheduledJobListResponse(BaseModel):
    timezone: str
    items: list[ScheduledJobRead] = Field(default_factory=list)


class ScheduledJobUpdateRequest(BaseModel):
    enabled: bool | None = None
    clock_time: str | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    interval_seconds: int | None = Field(default=None, ge=1, le=604800)
