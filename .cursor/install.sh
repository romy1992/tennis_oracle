#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for tennis_oracle.
# Prepares system packages, a local PostgreSQL, the Python backend venv,
# the frontend node_modules, and applies database migrations.
set -euo pipefail

# Run from the repository root regardless of where the script is invoked.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export DEBIAN_FRONTEND=noninteractive

echo "[install] Installing system packages (PostgreSQL, build tools)"
sudo apt-get update -qq
sudo apt-get install -y -qq \
  postgresql postgresql-contrib libpq-dev \
  python3-venv python3.12-venv \
  curl

echo "[install] Starting PostgreSQL for setup"
sudo pg_ctlcluster 16 main start 2>/dev/null || true
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q; then break; fi
  sleep 1
done

echo "[install] Ensuring postgres role password and tennis_db database"
sudo -u postgres psql -tAc "ALTER USER postgres PASSWORD 'postgres';"
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='tennis_db'" | grep -q 1; then
  sudo -u postgres createdb tennis_db
fi

echo "[install] Creating backend virtualenv and installing dependencies"
python3 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip
backend/.venv/bin/pip install -r backend/requirements-dev.txt

echo "[install] Ensuring backend runtime config files exist"
[ -f backend/.env ] || cp backend/.env.example backend/.env
[ -f backend/properties/config.env ] || cp backend/properties/config.env.example backend/properties/config.env

echo "[install] Applying database migrations"
( cd backend && .venv/bin/alembic upgrade head )

echo "[install] Installing frontend dependencies"
( cd frontend && npm ci )
[ -f frontend/.env ] || cp frontend/.env.example frontend/.env

echo "[install] Done"
