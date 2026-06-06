#!/usr/bin/env bash
# Esegui dal root del progetto tennis_oracle (ad es. in cron alle 09:00)
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
mkdir -p logs
python3 scripts/run_import_fixtures_report_backup.py >> logs/import_fixtures_report_backup.log 2>&1
