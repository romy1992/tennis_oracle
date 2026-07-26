#!/usr/bin/env bash
# Cron-friendly PostgreSQL backup (timestamped dump, retention, optional GPG, alerts).
# Credentials: DATABASE_URL or PG* / POSTGRES_* via env / config.env — never in this file.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-}:$ROOT"
exec python3 -m backend.src.jobs.run_db_backup --alert "$@"
