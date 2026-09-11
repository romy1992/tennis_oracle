from logging.config import fileConfig
import os
import sys
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Alembic is run from backend/; add repo root so `backend.*` imports resolve.
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.db.base import (  # noqa: E402
    AdminUser,
    Base,
    BettingSlip,
    BettingSlipDay,
    BettingSlipPick,
    Event,
    FeatureFlag,
    FeatureSnapshot,
    Fixture,
    GlobalUpdateRun,
    GlobalUpdateRunItem,
    MLMatch,
    MLPlayer,
    MLTournament,
    MatchPrediction,
    NextFixture,
    OddsSnapshot,
    Player,
    PrematchOddsSnapshot,
    PublishedPrediction,
    RankingSnapshot,
    RateLimitBucket,
    RuntimeSecret,
    ScheduledJobSetting,
    Standing,
    AccessLog,
    Entitlement,
    PaymentEvent,
    Plan,
    Subscription,
    TelegramBotEvent,
    TelegramFeedback,
    TelegramNotificationDelivery,
    TelegramUser,
    Tournament,
    User,
    WeeklyBetaReport,
    WalkForwardFold,
    WalkForwardRun,
)
from backend.src.app.core.env_files import load_backend_env_files  # noqa: E402

_ = (
    AdminUser,
    Event,
    FeatureFlag,
    Tournament,
    Fixture,
    NextFixture,
    MatchPrediction,
    PrematchOddsSnapshot,
    PublishedPrediction,
    BettingSlip,
    BettingSlipDay,
    BettingSlipPick,
    GlobalUpdateRun,
    GlobalUpdateRunItem,
    Standing,
    Player,
    User,
    Plan,
    Subscription,
    Entitlement,
    PaymentEvent,
    AccessLog,
    TelegramBotEvent,
    TelegramFeedback,
    TelegramNotificationDelivery,
    TelegramUser,
    WeeklyBetaReport,
    WalkForwardFold,
    WalkForwardRun,
    RateLimitBucket,
    RuntimeSecret,
    ScheduledJobSetting,
    FeatureSnapshot,
    MLMatch,
    MLPlayer,
    MLTournament,
    OddsSnapshot,
    RankingSnapshot,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Keep backend/.env as primary source of secrets; config.env is fallback only.
# Do not override Compose/container DATABASE_URL (host.docker.internal / db).
load_backend_env_files(override=False)

database_url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_SOURCE_URL")
if database_url:
    # Escape % for ConfigParser interpolation used by Alembic.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
