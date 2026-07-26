#!/usr/bin/env bash
# Cron-friendly wrapper for operational checks + admin alerts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-}:$ROOT"
exec python3 -m backend.src.jobs.run_ops_checks --alert "$@"
