#!/usr/bin/env bash
# Esegui dalla cartella backend (ad es. in cron alle 09:00)
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
mkdir -p logs
python3 -m src.jobs.daily_pipeline >> logs/daily_pipeline.log 2>&1
