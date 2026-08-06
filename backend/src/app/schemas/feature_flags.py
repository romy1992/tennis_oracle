"""Schemas for admin-managed runtime feature flags."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FeatureFlagRead(BaseModel):
    key: str
    enabled: bool
    description: str | None = None
    updated_at: datetime
    updated_by: str | None = None


class FeatureFlagListResponse(BaseModel):
    items: list[FeatureFlagRead] = Field(default_factory=list)


class FeatureFlagUpdateRequest(BaseModel):
    enabled: bool

