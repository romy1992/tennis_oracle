"""Pydantic schemas for Telegram beta user management."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TelegramUserStatus = Literal["invited", "active", "suspended", "blocked"]


class TelegramUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_user_id: int
    chat_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    status: TelegramUserStatus | str
    invite_origin: str | None = None
    first_access_at: datetime
    last_access_at: datetime
    terms_accepted: bool
    terms_accepted_at: datetime | None = None
    terms_version: str | None = None
    notifications_enabled: bool = True
    notify_predictions: bool = True
    notify_results: bool = True
    notify_empty_day: bool = False
    created_at: datetime
    updated_at: datetime


class TelegramUserListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TelegramUserRead]


class TelegramUserInviteCreate(BaseModel):
    """Pre-register a user on the whitelist (status=invited by default)."""

    telegram_user_id: int = Field(..., gt=0)
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    invite_origin: str | None = Field(default=None, max_length=255)
    status: TelegramUserStatus = "invited"


class TelegramUserAccessResult(BaseModel):
    """Centralized access-check payload (bot / internal)."""

    allowed: bool
    status: TelegramUserStatus | str | None = None
    reason: str | None = None
    terms_required: bool = False
    terms_accepted: bool = False
    user: TelegramUserRead | None = None


class TelegramNotificationPreferencesUpdate(BaseModel):
    """Partial update of push notification preferences (bot /notifiche)."""

    notifications_enabled: bool | None = None
    notify_predictions: bool | None = None
    notify_results: bool | None = None
    notify_empty_day: bool | None = None
