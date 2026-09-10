"""Schemas for protected runtime provider settings."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, SecretStr


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
