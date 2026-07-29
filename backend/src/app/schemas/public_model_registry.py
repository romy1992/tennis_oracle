"""Pydantic schemas for the official public model registry (ML-07)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

PublicModelRegistryStatus = Literal["candidate", "active", "retired"]


class PublicModelRegistryArtifacts(BaseModel):
    model_pkl: str | None = None
    metrics_path: str | None = None
    model_exists: bool = False
    metrics_exists: bool = False
    walk_forward_run_id: int | None = None
    calibration_run_id: int | None = None
    calibration_artifacts: dict[str, str] = Field(default_factory=dict)


class PublicModelRegistryEntryRead(BaseModel):
    id: int
    model_version: str
    model_name: str
    status: PublicModelRegistryStatus
    activated_at: datetime | None = None
    retired_at: datetime | None = None
    approval_metrics: dict[str, Any] = Field(default_factory=dict)
    motivation: str | None = None
    artifacts: PublicModelRegistryArtifacts
    supersedes_entry_id: int | None = None
    walk_forward_run_id: int | None = None
    calibration_run_id: int | None = None
    created_at: datetime
    created_by: str
    updated_at: datetime


class PublicModelRegistryActiveRead(BaseModel):
    """Active public model for bot/live publication consumers."""

    model_version: str
    model_name: str
    registry_entry_id: int
    activated_at: datetime | None = None
    source: Literal["registry"] = "registry"


class PublicModelRegistryListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PublicModelRegistryEntryRead]
    active: PublicModelRegistryEntryRead | None = None


class PublicModelRegistryCandidateCreate(BaseModel):
    model_version: str = Field(min_length=1, max_length=8)
    model_name: str = Field(min_length=1, max_length=64)
    motivation: str | None = Field(default=None, max_length=4000)
    approval_metrics: dict[str, Any] | None = None
    walk_forward_run_id: int | None = None
    calibration_run_id: int | None = None


class PublicModelRegistryActivateRequest(BaseModel):
    motivation: str = Field(min_length=1, max_length=4000)


class PublicModelRegistryRollbackRequest(BaseModel):
    motivation: str = Field(min_length=1, max_length=4000)


class PublicModelRegistryActionResponse(BaseModel):
    entry: PublicModelRegistryEntryRead
    previous_active: PublicModelRegistryEntryRead | None = None
    message: str
