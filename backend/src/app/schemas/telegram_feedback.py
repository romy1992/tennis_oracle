"""Pydantic schemas for Telegram feedback inbox."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TelegramFeedbackCategory = Literal[
    "bug",
    "content",
    "ux",
    "feature",
    "access",
    "other",
]
TelegramFeedbackStatus = Literal["new", "reviewing", "resolved", "rejected"]


class TelegramFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    category: TelegramFeedbackCategory | str
    rating: int
    message: str
    status: TelegramFeedbackStatus | str
    created_at: datetime
    updated_at: datetime


class TelegramFeedbackListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TelegramFeedbackRead]


class TelegramFeedbackStatusUpdate(BaseModel):
    status: TelegramFeedbackStatus


class TelegramFeedbackCreate(BaseModel):
    """Internal create payload used by the bot (not a public user API)."""

    telegram_user_id: int = Field(..., gt=0)
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    category: TelegramFeedbackCategory
    rating: int = Field(..., ge=1, le=5)
    message: str = Field(..., min_length=1, max_length=2000)
