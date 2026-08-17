"""Schemas for the admin live-beta dashboard aggregate."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.src.app.schemas.global_update import GlobalUpdateRunRead
from backend.src.app.schemas.imports import ImportStatusResponse
from backend.src.app.schemas.published_prediction import (
    OddsBand,
    PredictionMarket,
    PublishedLiveStatsSummary,
    PublishedSettledTipRead,
)
from backend.src.app.schemas.telegram_analytics import TelegramBotStatsResponse


LivePublicationEmptyReason = Literal[
    "ok",
    "table_unavailable",
    "publication_disabled",
    "public_model_unconfigured",
    "public_model_invalid",
    "pipeline_never_run",
    "pipeline_run_no_qualified_plays",
    "publication_errors",
]


class LiveBetaPipelineStatus(BaseModel):
    """Global update + import freshness for the live beta ops panel."""

    mode: Literal["live"] = "live"
    active_run: GlobalUpdateRunRead | None = None
    latest_run: GlobalUpdateRunRead | None = None
    last_updated_at: datetime | None = None
    import_status: ImportStatusResponse


class LiveBetaDataCompleteness(BaseModel):
    """Coverage checks on published tips and prematch odds snapshots."""

    tips_total: int = 0
    tips_with_odds: int = 0
    tips_with_odds_pct: float | None = None
    tips_with_event_date: int = 0
    tips_with_event_date_pct: float | None = None
    tips_with_match_context: int = 0
    tips_with_match_context_pct: float | None = None
    distinct_event_keys: int = 0
    event_keys_with_odds_snapshot: int = 0
    odds_snapshot_coverage_pct: float | None = None
    snapshots_opening: int = 0
    snapshots_observed: int = 0
    snapshots_publication: int = 0
    snapshots_closing: int = 0
    tips_with_closing_snapshot: int = 0
    tips_with_closing_snapshot_pct: float | None = None
    closing_odds_status: Literal["available", "partial", "missing", "unknown"] = "unknown"
    closing_odds_note: str | None = None


class LiveBetaPublicationHealth(BaseModel):
    """Operational diagnosis when the live tip registry is empty or partial."""

    empty_reason: LivePublicationEmptyReason = "ok"
    message: str
    live_publication_enabled: bool = False
    public_model_version: str | None = None
    public_model_name: str | None = None
    validation_started_at: datetime | None = None
    last_run_publications_created: int | None = None
    last_run_duplicates_skipped: int | None = None
    last_run_excluded: int | None = None
    last_run_candidates: int | None = None
    last_run_publication_errors: list[str] = Field(default_factory=list)


class LiveBetaRecentError(BaseModel):
    source: Literal["global_update", "telegram"]
    created_at: datetime | None = None
    message: str
    detail: str | None = None


class LiveBetaBacktestNote(BaseModel):
    """Explicit separation: backtest/training metrics are not mixed into live KPIs."""

    mode: Literal["backtest"] = "backtest"
    included_in_live_kpis: bool = False
    message: str = (
        "I KPI LIVE della beta usano solo il registro immutabile delle pubblicazioni. "
        "Metriche di training/backtest e previsioni operative restano sulle pagine dedicate."
    )
    related_paths: list[str] = Field(
        default_factory=lambda: [
            "/prediction-stats",
            "/betting-slip-model-stats",
            "/published-live-stats",
        ]
    )


class LiveBetaDashboardResponse(BaseModel):
    mode: Literal["live"] = "live"
    generated_at: datetime
    from_date: date | None = None
    to_date: date | None = None
    model_version: str | None = None
    model_name: str | None = None
    tournament_name: str | None = None
    surface: str | None = None
    odds_band: OddsBand | None = None
    latest_only: bool = True
    market: PredictionMarket = "match_winner"
    include_archived: bool = False
    official_only: bool = False

    pipeline: LiveBetaPipelineStatus
    publication_health: LiveBetaPublicationHealth
    live_stats: PublishedLiveStatsSummary
    official_live_stats: PublishedLiveStatsSummary
    published_today: list[PublishedSettledTipRead]
    open_predictions: list[PublishedSettledTipRead]
    closed_predictions: list[PublishedSettledTipRead]
    bot_usage: TelegramBotStatsResponse
    data_completeness: LiveBetaDataCompleteness
    recent_errors: list[LiveBetaRecentError]
    backtest: LiveBetaBacktestNote
