#!/usr/bin/env bash
# Esegui dalla root del repository (ad es. in cron alle 09:00)
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
mkdir -p backend/logs
python3 -m backend.src.jobs.daily_pipeline --days-forward 10 >> backend/logs/daily_pipeline.log 2>&1
