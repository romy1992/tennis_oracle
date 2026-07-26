#!/usr/bin/env bash
# Esegui dalla root del repository (ad es. in cron alle 09:00).
# Usa lo stesso orchestratore del pulsante UI "Aggiorna tutto".
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
mkdir -p backend/logs
python3 -m backend.src.jobs.run_global_update --days-forward 10 \
  >> backend/logs/daily_pipeline.log 2>&1
