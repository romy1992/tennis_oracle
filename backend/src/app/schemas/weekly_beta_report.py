"""Schemas for weekly beta report compute / API / persistence."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.src.app.schemas.telegram_analytics import TelegramBotActionCount


TelegramDeliveryStatus = Literal["pending", "sent", "skipped", "failed"]


class WeeklyBetaMetricDelta(BaseModel):
    """Current vs previous week numeric comparison."""

    current: float | int | None = None
    previous: float | int | None = None
    delta: float | int | None = None
    delta_pct: float | None = None


class WeeklyBetaUsersMetrics(BaseModel):
    total_users: int = 0
    active_users: int = 0
    new_users: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    retention_cohort: int = 0
    retention_retained: int = 0
    retention_pct: float | None = None


class WeeklyBetaCommandUsage(BaseModel):
    total_events: int = 0
    unique_users: int = 0
    by_action: list[TelegramBotActionCount] = Field(default_factory=list)


class WeeklyBetaLiveTipsMetrics(BaseModel):
    predictions_published: int = 0
    closed: int = 0
    open: int = 0
    won: int = 0
    lost: int = 0
    void: int = 0
    hit_rate_pct: float | None = None
    stake_settled: float = 0.0
    profit: float = 0.0
    roi_pct: float | None = None
    yield_pct: float | None = None
    max_drawdown: float = 0.0


class WeeklyBetaPipelineMetrics(BaseModel):
    runs_total: int = 0
    runs_failed: int = 0
    runs_completed_with_errors: int = 0
    runs_interrupted: int = 0
    combinations_failed: int = 0
    error_messages: list[str] = Field(default_factory=list)


class WeeklyBetaNotificationsMetrics(BaseModel):
    total: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    pending: int = 0
    by_kind_failed: dict[str, int] = Field(default_factory=dict)


class WeeklyBetaFeedbackMetrics(BaseModel):
    total: int = 0
    avg_rating: float | None = None
    by_status: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)


class WeeklyBetaPeriodMetrics(BaseModel):
    """All KPIs for a single week window."""

    week_start: date
    week_end: date
    week_label: str
    users: WeeklyBetaUsersMetrics
    command_usage: WeeklyBetaCommandUsage
    live_tips: WeeklyBetaLiveTipsMetrics
    pipeline: WeeklyBetaPipelineMetrics
    notifications: WeeklyBetaNotificationsMetrics
    feedback: WeeklyBetaFeedbackMetrics


class WeeklyBetaWowDeltas(BaseModel):
    """Week-over-week deltas for headline KPIs."""

    total_users: WeeklyBetaMetricDelta
    active_users: WeeklyBetaMetricDelta
    new_users: WeeklyBetaMetricDelta
    retention_pct: WeeklyBetaMetricDelta
    total_events: WeeklyBetaMetricDelta
    predictions_published: WeeklyBetaMetricDelta
    roi_pct: WeeklyBetaMetricDelta
    yield_pct: WeeklyBetaMetricDelta
    max_drawdown: WeeklyBetaMetricDelta
    pipeline_errors: WeeklyBetaMetricDelta
    notifications_failed: WeeklyBetaMetricDelta
    feedback_total: WeeklyBetaMetricDelta


class WeeklyBetaReportPayload(BaseModel):
    """Full computed report body stored in payload_json."""

    current: WeeklyBetaPeriodMetrics
    previous: WeeklyBetaPeriodMetrics
    wow: WeeklyBetaWowDeltas
    notes: list[str] = Field(default_factory=list)


class WeeklyBetaReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    week_start: date
    week_end: date
    week_label: str
    payload: WeeklyBetaReportPayload
    telegram_status: TelegramDeliveryStatus
    telegram_error: str | None = None
    telegram_sent_at: datetime | None = None
    generated_at: datetime
    generated_by: str


class WeeklyBetaReportListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    week_start: date
    week_end: date
    week_label: str
    telegram_status: TelegramDeliveryStatus
    telegram_sent_at: datetime | None = None
    generated_at: datetime
    generated_by: str
    # Headline KPIs for list cards (from payload).
    total_users: int = 0
    active_users: int = 0
    new_users: int = 0
    retention_pct: float | None = None
    predictions_published: int = 0
    roi_pct: float | None = None
    notifications_failed: int = 0
    feedback_total: int = 0


class WeeklyBetaReportListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[WeeklyBetaReportListItem]


class WeeklyBetaReportGenerateRequest(BaseModel):
    """Optional override: default is previous completed ISO week."""

    week_start: date | None = None
    send_telegram: bool = True
    force: bool = False


class WeeklyBetaReportGenerateResponse(BaseModel):
    report: WeeklyBetaReportRead
    created: bool
    telegram: dict[str, Any] = Field(default_factory=dict)
