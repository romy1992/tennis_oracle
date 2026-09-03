#!/usr/bin/env bash
# Per-boot reconciliation for tennis_oracle: bring up PostgreSQL and make sure
# the database exists and is migrated to head. Dependency installation lives in
# install.sh; this script only prepares runtime state and returns.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[start] Starting PostgreSQL"
sudo pg_ctlcluster 16 main start 2>/dev/null || true
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q; then break; fi
  sleep 1
done

echo "[start] Ensuring tennis_db exists"
sudo -u postgres psql -tAc "ALTER USER postgres PASSWORD 'postgres';" >/dev/null 2>&1 || true
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='tennis_db'" | grep -q 1; then
  sudo -u postgres createdb tennis_db
fi

if [ -x backend/.venv/bin/alembic ]; then
  echo "[start] Applying pending migrations"
  ( cd backend && .venv/bin/alembic upgrade head )
fi

echo "[start] Ready"
