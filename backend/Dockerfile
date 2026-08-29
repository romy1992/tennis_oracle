# syntax=docker/dockerfile:1
# Multi-stage backend image for tennis_oracle (API, Alembic, bot, jobs).
# Build context: repository root.
# Bakes only the audited production-serving model artifacts listed below.
# Datasets, historical/experimental models, logs, and secrets remain excluded.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------------------
# Builder: install runtime deps into an isolated venv
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY backend/requirements.txt ./requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Runtime: lean image with app code only
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    APP_HOME=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 libgomp1 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Application code (datasets/models/logs/secrets excluded via .dockerignore)
COPY backend/alembic.ini backend/alembic.ini
COPY backend/alembic backend/alembic
COPY backend/src backend/src
COPY backend/scripts backend/scripts
COPY backend/properties/config.env.example backend/properties/config.env.example

# Railway does not mount the local models directory. Keep this allowlist
# intentionally narrow: these are the three artifacts used by the active
# Match Winner, First Set Winner, and Over/Under serving pipelines.
COPY backend/data/models/v4/voting_ensemble.pkl backend/data/models/v4/voting_ensemble.pkl
COPY backend/data/models/first_set_winner_v2/logistic_regression.pkl backend/data/models/first_set_winner_v2/logistic_regression.pkl
COPY backend/data/models/over_under_games_v1/random_forest.pkl backend/data/models/over_under_games_v1/random_forest.pkl

# Compressed active v3 feature dataset used by Railway Dev walk-forward.
# Historical datasets remain excluded from the image.
COPY backend/data/processed/tennis_winner_dataset_with_odds_v3.csv.gz backend/data/processed/tennis_winner_dataset_with_odds_v3.csv.gz

# Empty dirs for optional bind-mounts and generated runtime data.
RUN mkdir -p backend/data/models backend/data/processed backend/data/reports backend/logs \
    && chown -R app:app /app

USER app

WORKDIR /app

EXPOSE 8000

# Default: API. Override for migrate / bot / jobs (see docker-compose).
# Alembic runs with working_dir=/app/backend; bot/jobs use PYTHONPATH=/app.
# Railway injects PORT; local Docker/Compose keeps the 8000 fallback.
# Health checks are configured per service so the same image can also run the
# non-HTTP Telegram bot without inheriting an API-only image health check.
CMD ["sh", "-c", "exec uvicorn backend.src.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
