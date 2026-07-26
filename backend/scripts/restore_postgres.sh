#!/usr/bin/env bash
# PostgreSQL restore wrapper. Default CLI mode is dry-run (no DB writes).
# Use --mode test for a safe rehearsal DB, or --mode overwrite --overwrite-source --yes for DR.
# Credentials: DATABASE_URL or PG* / POSTGRES_* via env / config.env — never in this file.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-}:$ROOT"
exec python3 -m backend.src.jobs.run_db_restore "$@"
