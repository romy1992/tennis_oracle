from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]

# Test / runtime override (middleware and non-DI callers honour this).
_settings_override: "Settings | None" = None


class Settings(BaseSettings):
    app_env: str = "local"
    debug: bool = False
    database_url: str = "postgresql://postgres:postgres@localhost:5432/tennis_db"
    api_prefix: str = "/api"
    global_update_cron_enabled: bool = False
    global_update_cron_time: str = "02:00"
    global_update_cron_timezone: str = "Europe/Rome"
    # Production: keep false. Concurrent runs are blocked by DB pipeline_lock.
    global_update_allow_concurrent_runs: bool = False
    # Step reliability (shared by API thread and CLI job worker).
    global_update_step_retries: int = 2
    global_update_retry_backoff_seconds: float = 5.0
    global_update_step_timeout_seconds: int = 3600
    global_update_lock_ttl_seconds: int = 21600
    # Prefer external cron/job in production; in-app scheduler stays optional.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ]
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1):\d+$"

    # Admin auth (JWT). Never commit real secrets; set via env / config.env.
    admin_jwt_secret: str = ""
    admin_jwt_expire_minutes: int = 480
    # Optional bootstrap credentials used only when admin_user table is empty.
    admin_username: str | None = None
    admin_password: str | None = None
    # Separate bot/service protection (X-Service-Token). Not an admin JWT.
    # Set via SERVICE_API_KEY only; never hard-code. Rotate with SERVICE_API_KEY_PREVIOUS.
    service_api_key: str | None = None
    # Optional previous key accepted during rotation (SERVICE_API_KEY_PREVIOUS).
    service_api_key_previous: str | None = None
    # When SERVICE_API_KEY is empty, allow anonymous reads on bot-shared endpoints.
    allow_unauthenticated_service_reads: bool = True

    # Rate limiting (PostgreSQL-backed; shared across API replicas + Telegram bot).
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    # Per-IP for unauthenticated / public requests.
    rate_limit_public: int = 60
    # Per admin JWT fingerprint.
    rate_limit_admin: int = 300
    # Per service-token fingerprint (bot → API).
    rate_limit_internal: int = 600
    # Extra quota for expensive paths (imports, global-update, login, …).
    rate_limit_expensive: int = 20
    # Stricter public login anti-bruteforce (per IP).
    rate_limit_login: int = 10
    # Telegram bot: per telegram_user_id.
    rate_limit_telegram: int = 30
    rate_limit_telegram_expensive: int = 10

    # Telegram beta users (whitelist + terms). Used by API admin and bot process.
    # When true (default), only status=active users may use privileged commands.
    telegram_whitelist_enabled: bool = True
    # When true, users must accept terms (version below) before privileged commands.
    telegram_terms_required: bool = False
    telegram_terms_version: str = "1"

    # Outbound Telegram user notifications (job run_telegram_notifications).
    # Admin pipeline alerts use OPS_ALERTS_* separately.
    telegram_notifications_enabled: bool = False
    telegram_notify_predictions_enabled: bool = True
    telegram_notify_results_enabled: bool = True
    telegram_notify_empty_day_enabled: bool = True
    # Pace outbound Bot API sends (Telegram ~30 msg/s; keep conservative).
    telegram_notify_min_interval_seconds: float = 0.05
    telegram_notify_max_retries: int = 2
    telegram_notify_retry_backoff_seconds: float = 2.0

    # Weekly beta report admin Telegram summary (job run_weekly_beta_report).
    # Uses TELEGRAM_BOT_TOKEN + TELEGRAM_ADMIN_CHAT_ID; independent of OPS_ALERTS_ENABLED.
    weekly_beta_report_telegram_enabled: bool = True

    # Walk-forward temporal validation (job run_walk_forward / API /walk-forward).
    # Separate from holdout baseline metrics and live/public model selection.
    # Default: observe latest run in global-update report; do not retrain inside daily update.
    walk_forward_in_global_update: bool = False
    walk_forward_mode: str = "expanding"  # expanding | rolling
    walk_forward_initial_train_days: int = 365
    walk_forward_test_days: int = 90
    walk_forward_step_days: int = 90
    walk_forward_min_train_rows: int = 200
    walk_forward_min_test_rows: int = 50
    walk_forward_embargo_days: int = 0
    walk_forward_edge_threshold: float = 0.03
    walk_forward_random_state: int = 42

    # Probability calibration (job run_calibration / API /calibration).
    # Uses walk-forward OOS data; does not activate on public model automatically.
    calibration_n_bins: int = 10
    calibration_min_bin_samples: int = 30
    calibration_min_calibrator_train_samples: int = 100

    # Temporary public-model config for live tip publication (until ML-07).
    # Default: automatic publication disabled. No silent fallback to another model.
    live_publication_enabled: bool = False
    public_model_version: str | None = None
    public_model_name: str | None = None

    # --- Observability (provider-agnostic; see docs/MONITORING.md) ---
    # text | json
    log_format: str = "text"
    # none | memory | prometheus
    metrics_provider: str = "memory"
    # none | logging | sentry | webhook
    error_tracking_provider: str = "none"
    error_tracking_dsn: str | None = None
    error_tracking_webhook_url: str | None = None
    # Admin alerts (Telegram Bot API + optional webhook). Fail-open.
    ops_alerts_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_admin_chat_id: str | None = None
    ops_alert_webhook_url: str | None = None
    ops_alert_cooldown_seconds: int = 300
    # Operational check thresholds (import / predictions / duration).
    ops_import_max_age_hours: int = 36
    ops_predictions_lookback_hours: int = 36
    ops_pipeline_max_duration_seconds: int = 7200
    # Expose GET /metrics when metrics_provider is memory|prometheus.
    metrics_endpoint_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=(
            ROOT_DIR / "properties" / "config.env",
            ROOT_DIR / ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def _cached_settings() -> Settings:
    return Settings()


def get_settings() -> Settings:
    if _settings_override is not None:
        return _settings_override
    return _cached_settings()


def set_settings_override(settings: Settings | None) -> None:
    """Override settings for tests (or temporary runtime). Pass ``None`` to clear."""
    global _settings_override
    _settings_override = settings
    _cached_settings.cache_clear()
