# tennis_oracle — documentazione tecnica

[![CI](https://github.com/romy1992/tennis_oracle/actions/workflows/ci.yml/badge.svg)](https://github.com/romy1992/tennis_oracle/actions/workflows/ci.yml)

Monorepo **backend FastAPI** (`backend/`) + **frontend React** (`frontend/`).

Il backend importa dati tennis da API esterna in PostgreSQL (`tennis_db`), espone API REST, genera previsioni ML, schedine e sincronizza opzionalmente verso un DB target.

| Documento | Pubblico |
|-----------|----------|
| **Questo file** | Sviluppatori: architettura, classi, metodi, API, ML |
| [docs/GUIDA_UTENTE.md](docs/GUIDA_UTENTE.md) | Utente medio: cosa fa il prodotto e come usarlo |
| [docs/DOCKER.md](docs/DOCKER.md) | Docker: compose locale/prod/dev hot-reload, migrate, bot, job, rebuild BE/FE |
| [docs/STAGING.md](docs/STAGING.md) | Staging: DB separato, CORS/HTTPS-ready, migrazioni controllate, smoke, deploy/rollback |
| [docs/SCHEDULING.md](docs/SCHEDULING.md) | Job giornaliero, cron, sync cloud |
| [docs/MONITORING.md](docs/MONITORING.md) | Monitoring: log JSON, correlation ID, metriche, error tracking, alert, ops checks |
| [docs/BACKUP_DR.md](docs/BACKUP_DR.md) | Backup/restore PostgreSQL, retention, cifratura GPG, disaster recovery |
| [docs/ARCHITECTURE_LAYERS.md](docs/ARCHITECTURE_LAYERS.md) | Layer `app/services` vs `service` vs `repository` vs `entity`; piano migrazione |

> **Manutenzione docs**: ad ogni modifica rilevante di codice, aggiornare questo README e/o la guida utente (regola Cursor `.cursor/rules/keep-docs-updated.mdc`).

---

## Indice

1. [Architettura](#1-architettura)
2. [Setup](#2-setup)
3. [API REST](#3-api-rest)
4. [Backend — riferimento classi e metodi](#4-backend--riferimento-classi-e-metodi)
5. [Frontend — riferimento moduli](#5-frontend--riferimento-moduli)
6. [Pipeline ML](#6-pipeline-ml)
7. [Import, job e sync](#7-import-job-e-sync)
8. [Bot Telegram](#8-bot-telegram)
9. [Schema dati](#9-schema-dati)
10. [CI (GitHub Actions)](#10-ci-github-actions)
11. [Docker](#11-docker)

---

## 1. Architettura

```text
┌─────────────┐     HTTP      ┌──────────────────┐     SQL      ┌────────────┐
│  Frontend   │ ────────────► │  FastAPI (main)  │ ──────────► │ PostgreSQL │
│  React/Vite │               │  /api/*          │             │ tennis_db  │
└─────────────┘               └────────┬─────────┘             └─────▲──────┘
                                       │                             │
                          ┌────────────┼────────────┐                │
                          ▼            ▼            ▼                │
                     services/    predictor/   import_*  ◄── API Tennis
                          │            │            │
                          └────────────┴────────────┘
                                       │
                              global_update / scheduler
                                       │
                              jobs/run_global_update ──sync──► DB cloud (opz.)
```

**Layer backend (ordine tipico della richiesta):**

1. `api/routes/*` — endpoint HTTP
2. `app/services/*` — logica applicativa (**canonico** per nuovo codice di dominio)
3. `entity/*` + `app/models/*` — ORM SQLAlchemy (`app/models` re-esporta molte entity + modelli ML)
4. `service/*` + `repository/*` — import API tennis + CRUD legacy (ancora attivi; orchestrati da `app/services/imports` e `global_update`)
5. `app/ml/*` — dataset, training, inferenza

**Sessione DB:** un solo `engine` / `SessionLocal` in `app/db/session.py`. Il modulo legacy `repository/base/repository_db.py` li re-esporta (niente secondo pool). Dettaglio, duplicazioni e piano step-by-step: [docs/ARCHITECTURE_LAYERS.md](docs/ARCHITECTURE_LAYERS.md).

---

## 2. Setup

### Requisiti runtime

| Stack | Versione supportata |
|-------|---------------------|
| **Python** | **3.12**, **3.13** o **3.14** (file `.python-version` → `3.12`) |
| **Node.js** | **^20.19.0** oppure **>=22.12.0** (richiesto da Vite 8; vedi `frontend/package.json` → `engines` e `frontend/.nvmrc`) |
| **PostgreSQL** | database `tennis_db` |

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt          # solo runtime
# oppure, per sviluppo/test:
pip install -r requirements-dev.txt      # runtime + pytest
cp properties/config.env.example properties/config.env   # se usi gli import API
# configura anche backend/.env (non committare segreti)
alembic upgrade head
uvicorn src.app.main:app --reload
```

Dipendenze: `backend/requirements.txt` (runtime, versioni pinate) e `backend/requirements-dev.txt` (include runtime + `pytest` + `pytest-cov`).

Variabili minime in `backend/.env`:

```env
APP_ENV=local
DEBUG=false
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tennis_db
CORS_ORIGINS=["http://localhost:5173","http://localhost:5174","http://127.0.0.1:5173","http://127.0.0.1:5174"]
CORS_ORIGIN_REGEX=^https?://(localhost|127\.0\.0\.1):\d+$
ADMIN_JWT_SECRET=change-me-to-a-long-random-secret
ADMIN_JWT_EXPIRE_MINUTES=480
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me-strong-password
SERVICE_API_KEY=
# Optional previous key during rotation; clear after bot uses the new key.
SERVICE_API_KEY_PREVIOUS=
ALLOW_UNAUTHENTICATED_SERVICE_READS=true
```

Rate limiting (contatori in PostgreSQL, condivisi tra repliche API e bot):

```env
RATE_LIMIT_ENABLED=true
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_PUBLIC=60
RATE_LIMIT_ADMIN=300
RATE_LIMIT_INTERNAL=600
RATE_LIMIT_EXPENSIVE=20
RATE_LIMIT_LOGIN=10
RATE_LIMIT_TELEGRAM=30
RATE_LIMIT_TELEGRAM_EXPENSIVE=10
```

- Pubbliche: per IP; admin: fingerprint JWT; interne: fingerprint `X-Service-Token`
- Endpoint costosi (login, imports, global-update, SMVA, regenerate schedine, …) hanno un quota aggiuntiva
- `/health` e `/ready` (e docs OpenAPI) sono esclusi
- Superato il limite: HTTP **429** con header `Retry-After`
- Bot Telegram: limite per `telegram_user_id` (più stretto su `/schedine`, `/partite`, `/statistiche`)

All’avvio, se la tabella `admin_user` è vuota e sono impostati `ADMIN_USERNAME` / `ADMIN_PASSWORD`, viene creato il primo admin (password con bcrypt). Non inserire segreti reali nel repo: usa `backend/properties/config.env.example` come modello.

Per gli import API tennis: `backend/properties/config.env` con `API_TENNIS_KEY`, `API_TENNIS_BASE` e opzionalmente `API_TENNIS_TIMEOUT` (secondi, default 30; vedi `config.env.example`). I log applicativi oscurano automaticamente chiavi e credenziali nelle URL/query.

Bot Telegram (opzionale), stessi file `.env` / `config.env`:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_API_BASE_URL=http://localhost:8000/api
TELEGRAM_SERVICE_API_KEY=
TELEGRAM_MODEL_VERSION=v3
TELEGRAM_MODEL_NAME=logistic_regression
TELEGRAM_MODEL_NAMES=logistic_regression,random_forest
TELEGRAM_DEFAULT_STAKE=10
TELEGRAM_SLIP_COUNT=9
TELEGRAM_MIN_EDGE_PERCENT=2.0
TELEGRAM_FEEDBACK_URL=
```

Pubblicazione live nel registro `PublishedPrediction` (temporanea fino a ML-07; **default OFF**):

```env
LIVE_PUBLICATION_ENABLED=false
PUBLIC_MODEL_VERSION=
PUBLIC_MODEL_NAME=
```

Prima di abilitare: applicare migrazioni fino a `0015`, impostare esplicitamente versione/nome pubblici (es. `v3` / `logistic_regression`, allineati a ciò che mostri in produzione/bot), verificare un global-update e il report `summary.live_publication`. Nessun fallback silenzioso ad un’altra combo.

`TELEGRAM_SERVICE_API_KEY` deve coincidere con `SERVICE_API_KEY` quando quest’ultima è valorizzata (header `X-Service-Token`). Per ruotare: imposta la nuova chiave in `SERVICE_API_KEY`, lascia la vecchia in `SERVICE_API_KEY_PREVIOUS`, aggiorna `TELEGRAM_SERVICE_API_KEY` sul bot, poi rimuovi `SERVICE_API_KEY_PREVIOUS`.

Se lo schema esiste già senza Alembic: `alembic stamp head`.

### Frontend

```bash
cd frontend
npm ci          # installazione riproducibile da package-lock.json
# oppure: npm install  (se hai modificato package.json)
cp .env.example .env
npm run dev
```

```env
VITE_API_BASE_URL=http://localhost:8000
```

Versioning: nessuna dipendenza `latest` in `package.json`; lockfile allineato. Script utili: `npm run build`, `npm test` / `npm run test:watch` / `npm run test:coverage` (Vitest + jsdom + React Testing Library).

### Global update (job + optional in-app cron)

Produzione: job esterno (stesso orchestratore del pulsante UI):

```bash
python -m backend.src.jobs.run_global_update --days-forward 10
```

In `config.env` / `.env`:

```env
GLOBAL_UPDATE_CRON_ENABLED=false
GLOBAL_UPDATE_CRON_TIME=02:00
GLOBAL_UPDATE_CRON_TIMEZONE=Europe/Rome
GLOBAL_UPDATE_ALLOW_CONCURRENT_RUNS=false
GLOBAL_UPDATE_STEP_RETRIES=2
GLOBAL_UPDATE_RETRY_BACKOFF_SECONDS=5
GLOBAL_UPDATE_STEP_TIMEOUT_SECONDS=3600
GLOBAL_UPDATE_LOCK_TTL_SECONDS=21600
```

### Docker (locale / produzione)

Guida completa: [docs/DOCKER.md](docs/DOCKER.md).

```bash
cp .env.example .env          # DB host via host.docker.internal; secret in backend/.env
docker compose up --build -d  # migrate + api + frontend (db-1 spento)
# UI http://localhost:5173  —  API http://localhost:8000/health
# Postgres del PC deve essere acceso su 5432
docker compose down           # arresto (volume embedded conservato; non usare -v)
```

Comandi separati: `docker compose run --rm migrate`, `docker compose --profile bot up -d bot`, `docker compose --profile jobs run --rm job`. Postgres embedded (opzionale): `docker compose --profile embedded-db up -d db`. Overlay prod: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d`.

Dopo modifiche al codice (stack **prod-like**): `docker compose build api` / `build frontend` poi `up -d`. Per coding con hot-reload: [docs/DOCKER.md — modalità sviluppo](docs/DOCKER.md#modalità-sviluppo-hot-reload) (`docker-compose.dev.yml`). Dataset/modelli/log/segreti **non** finiscono nelle immagini; volume `postgres_data` solo se usi il profilo `embedded-db`. Sul host: modelli via `MODELS_HOST_PATH`, dataset CSV via `PROCESSED_HOST_PATH`, report via `REPORTS_HOST_PATH` (necessari per walk-forward in container).

Artefatti: `backend/Dockerfile`, `frontend/Dockerfile`, `.dockerignore`, `docker-compose.yml`, `docker-compose.dev.yml`, `docker-compose.prod.yml`, `docker-compose.staging.yml`.

Staging (porte 8001/5174, DB `tennis_db_staging`, `AUTO_MIGRATE`, bot dedicato): [docs/STAGING.md](docs/STAGING.md).

```bash
cp .env.staging.example .env.staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml --env-file .env.staging up --build -d
python backend/scripts/smoke_check.py --base-url http://localhost:8001 --frontend-url http://localhost:5174 --expect-env staging
```

---

## 3. API REST

Prefisso default: `/api` (`Settings.api_prefix`).  
Documentazione interattiva: `http://localhost:8000/docs`.

### Autenticazione

| Tipo | Uso | Header |
|------|-----|--------|
| Admin JWT | Dashboard React e operazioni privilegiate | `Authorization: Bearer <access_token>` |
| Service token | Autenticazione service-to-service bot→API (non utenti Telegram) | `X-Service-Token: <SERVICE_API_KEY>` |

- `POST /api/auth/login` — username/password → access token con scadenza (`ADMIN_JWT_EXPIRE_MINUTES`)
- `GET /api/auth/me` — verifica sessione admin (`require_admin`)
- `POST /api/auth/logout` — logout stateless (il client elimina il token)
- Dipendenze riutilizzabili: `require_admin`, `require_admin_or_service`, `require_service_token` in `app/api/deps.py`
- Confronto chiave con `hmac.compare_digest`; errori generici (`Not authenticated`); la chiave non viene scritta nei log
- Rotazione: `SERVICE_API_KEY` (corrente) + opzionale `SERVICE_API_KEY_PREVIOUS`; il bot invia solo `TELEGRAM_SERVICE_API_KEY`
- Risposte: **401** non autenticato / token invalido; **403** autenticato ma non autorizzato (es. admin disabilitato, regenerate con solo service token); **429** rate limit superato (`Retry-After`)
- Con `SERVICE_API_KEY` vuoto e `ALLOW_UNAUTHENTICATED_SERVICE_READS=true` (default locale) i GET del bot restano aperti; in staging/produzione impostare la chiave e allineare `TELEGRAM_SERVICE_API_KEY`

### Rate limiting

Contatori fixed-window in tabella `rate_limit_bucket` (Alembic `0012_rate_limit_bucket`), quindi sicuri con più istanze API senza Redis.

| Componente | Ruolo |
|------------|-------|
| `app/core/rate_limit.py` | `consume_rate_limit`, fingerprint token, session factory (override nei test) |
| `app/middleware/rate_limit.py` | `RateLimitMiddleware` — tier public/admin/internal, esclusione health/deps/metrics, 429 + `Retry-After` |
| `app/middleware/correlation.py` | `CorrelationIdMiddleware` — `X-Correlation-ID` / `X-Request-ID` |
| `app/middleware/metrics.py` | `MetricsMiddleware` — contatori/latenze HTTP |
| `app/telegram/rate_limit.py` | Decorator `rate_limited` per comandi bot (messaggio IT) |

Abuso loggato con path / scope / IP o `telegram_user_id` senza token o password.

### Monitoring operativo

Provider-agnostic (`app/observability/`): log `text`/`json`, correlation ID, metriche in-process (scrape Prometheus), error tracking (`none`/`logging`/`sentry`/`webhook`), alert Telegram/webhook, check import/pronostici/durata. Guida produzione: [docs/MONITORING.md](docs/MONITORING.md).

### Montate in `api/router.py` (attive)

| Metodo | Path | Handler | Auth | Ruolo |
|--------|------|---------|------|-------|
| GET | `/health` | `health.health` | pubblica | Liveness (processo up) |
| GET | `/ready` | `health.ready` | pubblica | Readiness (DB raggiungibile; 503 se no) |
| GET | `/deps` | `health.dependencies` | pubblica | Stato dipendenze / canali monitoring (no secret) |
| GET | `/metrics` | `metrics.metrics` | pubblica* | Prometheus text se `METRICS_*` abilitato |
| GET | `/metrics.json` | `metrics.metrics_json` | pubblica* | Snapshot JSON metriche |
| POST | `/api/auth/login` | `auth.login` | pubblica | Login admin |
| GET | `/api/auth/me` | `auth.read_session` | admin | Verifica sessione |
| POST | `/api/auth/logout` | `auth.logout` | admin | Logout |
| GET | `/api/imports/status` | `imports.read_import_status` | admin | Ultimo stato import |
| POST | `/api/imports/refresh` | `imports.refresh_upcoming_matches` | admin | Refresh next fixtures + predizioni |
| POST | `/api/imports/fixtures` | `imports.import_completed_fixtures` | admin | Import partite giocate |
| GET | `/api/next-fixtures` | `predictions.read_next_fixtures` | admin o service | Prossime partite |
| GET | `/api/next-fixtures/predictions` | `predictions.read_next_fixtures_predictions` | admin o service | Partite + predizione paginate |
| GET | `/api/predictions/stats/daily` | `predictions.read_daily_prediction_stats` | admin | Stats giornaliere |
| GET | `/api/predictions/stats/summary` | `predictions.read_prediction_summary` | admin o service | Riepilogo accuracy/ROI |
| GET | `/api/single-match-value` | `single_match_value.read_single_match_value_analysis` | admin o service | Analisi value bet (margine globale default 2%) |
| GET | `/api/betting-slips/daily` | `betting_slips.read_daily_betting_slips` | admin o service (`regenerate=true` → solo admin) | Schedine del giorno (9 profili a tier) |
| POST | `/api/betting-slips/daily` | `betting_slips.generate_daily_betting_slips` | admin | Rigenera schedine del giorno |
| GET | `/api/betting-slips/calendar` | `betting_slips.read_betting_slip_calendar` | admin | Calendario giorni con schedine |
| POST | `/api/betting-slips/refresh` | `betting_slips.refresh_daily_betting_slips` | admin | Refresh import + rigenera schedine |
| GET | `/api/betting-slips/stats` | `betting_slips.read_betting_slip_stats` | admin | Stats schedine |
| GET | `/api/betting-slips/stats/by-model` | `betting_slips.read_betting_slip_stats_by_model` | admin o service | Stats per modello |
| POST | `/api/global-update` | `global_update.trigger_global_update` | admin | Avvia aggiornamento globale |
| GET | `/api/global-update/status` | `global_update.read_global_update_status` | admin | Run attiva |
| GET | `/api/global-update/latest` | `global_update.read_latest_global_update` | admin | Ultima run |
| GET | `/api/global-update/{run_id}` | `global_update.read_global_update_run` | admin | Dettaglio run |
| GET | `/api/global-update/{run_id}/report` | `global_update.read_global_update_report` | admin | Report run |
| POST | `/api/global-update/{run_id}/cancel` | `global_update.cancel_global_update_run` | admin | Annulla run |
| GET | `/api/models-versions/results` | `global_update.read_models_versions_results` | admin o service | Risultati per versione/modello |
| GET | `/api/telegram/events` | `telegram.read_telegram_events` | admin | Lista accessi/click bot (admin) |
| GET | `/api/telegram/stats` | `telegram.read_telegram_stats` | admin | Aggregati accessi bot (admin) |
| GET | `/api/telegram/users` | `telegram_users.search_telegram_users` | admin | Ricerca utenti beta (whitelist) |
| GET | `/api/telegram/users/{telegram_user_id}` | `telegram_users.read_telegram_user` | admin | Dettaglio utente beta |
| POST | `/api/telegram/users` | `telegram_users.create_telegram_user_invite` | admin | Pre-registra / invita utente |
| POST | `/api/telegram/users/{telegram_user_id}/activate` | `telegram_users.activate_user` | admin | Attiva accesso |
| POST | `/api/telegram/users/{telegram_user_id}/suspend` | `telegram_users.suspend_user` | admin | Sospende accesso |
| POST | `/api/telegram/users/{telegram_user_id}/block` | `telegram_users.block_user` | admin | Blocca accesso |
| GET | `/api/telegram/feedback` | `telegram_feedback.search_telegram_feedback` | admin | Inbox feedback bot |
| GET | `/api/telegram/feedback/{feedback_id}` | `telegram_feedback.read_telegram_feedback` | admin | Dettaglio feedback |
| PATCH | `/api/telegram/feedback/{feedback_id}` | `telegram_feedback.patch_telegram_feedback_status` | admin | Aggiorna stato (`new`/`reviewing`/`resolved`/`rejected`) |
| POST | `/api/published-predictions` | `published_predictions.create_published_prediction` | admin | Pubblica snapshot immutabile |
| GET | `/api/published-predictions` | `published_predictions.read_published_predictions` | admin | Storico pubblicazioni (filtri) |
| GET | `/api/published-predictions/stats` | `published_predictions.read_published_live_stats` | admin | Statistiche live tipbook (ledger immutabile; filtri periodo/modello/torneo/superficie/fascia quota) |
| GET | `/api/published-predictions/by-publication/{publication_id}` | `published_predictions.read_publication_versions` | admin | Catena versioni |
| GET | `/api/published-predictions/{id}` | `published_predictions.read_published_prediction` | admin | Dettaglio snapshot |
| POST | `/api/published-predictions/{id}/corrections` | `published_predictions.create_published_prediction_correction` | admin | Nuova versione (append-only) |
| GET | `/api/live-beta-dashboard` | `live_beta_dashboard.read_live_beta_dashboard` | admin | Dashboard aggregata beta live (pipeline, tipbook, bot, completezza, errori) |
| GET | `/api/weekly-beta-reports` | `weekly_beta_reports.list_reports` | admin | Storico report settimanali beta |
| GET | `/api/weekly-beta-reports/latest` | `weekly_beta_reports.read_latest_report` | admin | Ultimo report settimanale |
| GET | `/api/weekly-beta-reports/{report_id}` | `weekly_beta_reports.read_report` | admin | Dettaglio report (payload + WoW) |
| POST | `/api/weekly-beta-reports/generate` | `weekly_beta_reports.generate_report` | admin | Genera/rigenera report + opz. Telegram admin |
| GET | `/api/walk-forward` | `walk_forward.list_runs` | admin | Storico run walk-forward |
| GET | `/api/walk-forward/latest` | `walk_forward.read_latest_run` | admin | Ultima run walk-forward |
| POST | `/api/walk-forward/runs` | `walk_forward.trigger_run` | admin | Avvia walk-forward (background; non cambia modello pubblico) |
| GET | `/api/walk-forward/runs/{run_id}` | `walk_forward.read_run` | admin | Dettaglio run + fold/metriche/leakage |
| GET | `/api/calibration` | `calibration.list_runs` | admin | Storico run calibrazione probabilità |
| GET | `/api/calibration/latest` | `calibration.read_latest_run` | admin | Ultima run calibrazione |
| POST | `/api/calibration/runs` | `calibration.trigger_run` | admin | Avvia calibrazione OOS walk-forward (non attiva modello pubblico) |
| GET | `/api/calibration/runs/{run_id}` | `calibration.read_run` | admin | Dettaglio run + metriche/reliability/confronto metodi |
| GET | `/api/ops/checks` | `ops.get_ops_checks` | admin | Controlli operativi (import, pronostici, durata); `?alert=true` notifica admin |
| POST | `/api/prematch-odds-snapshots` | `prematch_odds_snapshots.create_prematch_odds_snapshot` | admin | Append singolo rilevamento quote |
| POST | `/api/prematch-odds-snapshots/from-payload` | `prematch_odds_snapshots.create_prematch_odds_snapshots_from_payload` | admin | Ingest matrice Home/Away |
| POST | `/api/prematch-odds-snapshots/from-fixture/{event_key}` | `prematch_odds_snapshots.create_prematch_odds_snapshots_from_fixture` | admin | Snapshot da odds JSON corrente |
| GET | `/api/prematch-odds-snapshots` | `prematch_odds_snapshots.read_prematch_odds_snapshots` | admin | Storico quote (filtri) |
| GET | `/api/prematch-odds-snapshots/{id}` | `prematch_odds_snapshots.read_prematch_odds_snapshot` | admin | Dettaglio snapshot |

\* `/metrics` e `/metrics.json` rispondono 404 se `METRICS_ENDPOINT_ENABLED=false` o `METRICS_PROVIDER=none`.

### Presenti nel codice ma non montate in `api_router` (legacy / opzionali)

Route definite in `matches.py`, `players.py`, `tournaments.py`, `ml.py` — **non** incluse in `backend/src/app/api/router.py` nella configurazione attuale. Per riattivarle: `api_router.include_router(...)`.

---

## 4. Backend — riferimento classi e metodi

### 4.1 Entry point e core

#### `app/main.py`

| Simbolo | Ruolo |
|---------|-------|
| `lifespan` | All’avvio: `reconcile_orphaned_runs`, `ensure_bootstrap_admin`, `start_global_update_scheduler`; allo shutdown ferma lo scheduler |
| `app` | Istanza FastAPI, middleware correlation/metrics/rate-limit, CORS, mount health/metrics + `api_router` |

#### `app/core/config.py` — `Settings`

Campi: `app_env`, `debug`, `database_url`, `api_prefix`, flag/cron global update, `cors_origins`, `cors_origin_regex`, auth admin (`admin_jwt_secret`, `admin_jwt_expire_minutes`, `admin_username`, `admin_password`), service token (`service_api_key`, `service_api_key_previous`, `allow_unauthenticated_service_reads`), rate limit (`rate_limit_enabled`, `rate_limit_window_seconds`, `rate_limit_public` / `_admin` / `_internal` / `_expensive` / `_login` / `_telegram` / `_telegram_expensive`), utenti beta Telegram (`telegram_whitelist_enabled`, `telegram_terms_required`, `telegram_terms_version`), notifiche push utente (`telegram_notifications_enabled`, `telegram_notify_predictions_enabled`, `telegram_notify_results_enabled`, `telegram_notify_empty_day_enabled`, `telegram_notify_min_interval_seconds`, `telegram_notify_max_retries`, `telegram_notify_retry_backoff_seconds`), walk-forward (`walk_forward_in_global_update`, `walk_forward_mode`, `walk_forward_initial_train_days`, `walk_forward_test_days`, `walk_forward_step_days`, `walk_forward_min_train_rows`, `walk_forward_min_test_rows`, `walk_forward_embargo_days`, `walk_forward_edge_threshold`, `walk_forward_random_state`), calibrazione (`calibration_n_bins`, `calibration_min_bin_samples`, `calibration_min_calibrator_train_samples`), pubblicazione live temporanea fino a ML-07 (`live_publication_enabled`, `public_model_version`, `public_model_name`; default pubblicazione disabilitata), observability (`log_format`, `metrics_provider`, `metrics_endpoint_enabled`, `error_tracking_*`, `ops_alerts_*`, `telegram_bot_token`, `telegram_admin_chat_id`, soglie `ops_*`).  
`get_settings()` — settings cacheati; `set_settings_override()` per test/middleware.

#### `app/core/security.py`

`hash_password` / `verify_password` (bcrypt), `create_access_token` / `decode_access_token` (JWT HS256).

#### `app/api/deps.py`

Dipendenze FastAPI: `require_admin`, `require_admin_or_service`, `require_service_token`.

#### `app/services/auth.py`

`authenticate_admin`, `issue_access_token`, `ensure_bootstrap_admin` (primo admin da env se tabella vuota).

#### `app/core/logging.py` / `app/observability/`

`configure_logging()` → `observability.setup.setup_observability`: log `text`/`json`, filter secret, correlation ID, metriche, error tracking.  
Moduli: `context`, `logging`, `metrics`, `errors`, `alerts`, `ops_checks`, `dependencies`, `notify`.  
Job CLI: `python -m backend.src.jobs.run_ops_checks [--alert]`. Dettagli: [docs/MONITORING.md](docs/MONITORING.md).  
Per URL/header/payload esterni usare sempre `utility/sensitive_data` (anche i filtri di log applicano `sanitize_text`).

#### `app/db/session.py`

`get_db()` — dependency FastAPI che yielda una `Session` SQLAlchemy.

#### `app/scheduler.py`

| Funzione | Ruolo |
|----------|-------|
| `_parse_cron_time` | Parse `HH:MM` |
| `_should_run_now` | True se ora corrente = target |
| `_scheduler_loop` | Loop background che a orario avvia `start_global_update` |
| `start_global_update_scheduler` | Avvia thread se `GLOBAL_UPDATE_CRON_ENABLED` |
| `stop_global_update_scheduler` | Ferma lo scheduler |

---

### 4.2 Entity (ORM di dominio)

Modulo `backend/src/entity/` (home canonica delle tabelle operative). `app/models` ne re-esporta molte per i service moderni.

| Classe | Tabella / ruolo |
|--------|-----------------|
| `Event` | Tipi evento |
| `Tournament` | Tornei (superficie in `tournament_sourface`) |
| `Fixture` | Partite storiche/completate |
| `NextFixture` | Partite future + odds JSON |
| `Player` | Giocatori |
| `Standing` | Classifica corrente (non usata come rank pre-match ML) |
| `MatchPrediction` | Predizione persistita (`event_key` + `model_version` + `model_name`) |
| `BettingSlip` / `BettingSlipDay` / `BettingSlipPick` | Schedine e selezioni; pick con campi value (`void_odds`, `min_edge_percent`, `value_decision`, …) |
| `GlobalUpdateRun` / `GlobalUpdateRunItem` | Stato aggiornamento globale e step per combo modello |
| `TelegramBotEvent` | Accessi/comandi bot (`telegram_bot_event`; migrazione `0010`) |
| `TelegramUser` | Utenti beta Telegram / whitelist (`telegram_user`; migrazione `0017` + prefs/chat_id in `0018`; stati `invited`/`active`/`suspended`/`blocked`) |
| `TelegramFeedback` | Feedback in-bot (`telegram_feedback`; migrazione `0019`; categoria, rating 1–5, messaggio, stati `new`/`reviewing`/`resolved`/`rejected`) |
| `WeeklyBetaReport` | Snapshot report settimanale beta (`weekly_beta_report`; migrazione `0020`; payload KPI + stato invio Telegram admin) |
| `TelegramNotificationDelivery` | Ledger consegna push (`telegram_notification_delivery`; migrazione `0018`; dedupe per utente/kind/giorno) |
| `PublishedPrediction` | Registro immutabile pronostici pubblicati (`published_prediction`; migrazione `0013`; versioni via `publication_id` + `content_version`) |
| `PrematchOddsSnapshot` | Storico append-only quote pre-match per bookmaker/selezione (`prematch_odds_snapshot`; migrazione `0014`; tipi `opening`/`observed`/`publication`/`closing`) |
| `AdminUser` | Account amministratore (`admin_user`; migrazione `0011`; solo hash password) |
| `RateLimitBucket` | Contatori rate limit multi-istanza (`rate_limit_bucket`; migrazione `0012`) |

Modelli ML canonici in `app/models/ml.py`: `MLPlayer`, `MLTournament`, `MLMatch`, `RankingSnapshot`, `OddsSnapshot`, `FeatureSnapshot`.

---

### 4.3 Repository (legacy import)

Usati dagli script in `service/import_*`. Le API di lettura passano da `app/services` + `get_db()`, non dai repository.

#### `repository/base/repository_db.py`

Re-export di `engine` e `SessionLocal` da `app.db.session` (compatibilità import path).

#### `repository/base/crud_repository.py` — `CrudRepository`

| Metodo | Ruolo |
|--------|-------|
| `save` | `merge` + commit (insert/update) |
| `save_all` | Insert massivo |
| `search_all` | Tutti i record |
| `search_column_values` | Valori colonna (opz. distinct) |
| `filter_by` | Query `filter_by` |
| `search_filter` | Filtri avanzati (OR, IN, None/not None) |
| `update` | Aggiorna un campo su match filtro |
| `delete` / `delete_by_filters` | Cancellazione |
| `massive_update_bulk` | `bulk_update_mappings` |

Repository specializzati (eredita `CrudRepository`):  
`EventRepository`, `FixtureRepository`, `NextFixtureRepository`, `PlayerRepository`, `StandingRepository`, `TournamentsRepository`, `MatchPredictionRepository`.

---

### 4.4 Services applicativi

#### `app/services/predictions.py`

| Funzione | Ruolo |
|----------|-------|
| `list_next_fixtures` / `count_next_fixtures` | Query next fixtures filtrate |
| `list_played_fixtures` / `count_played_fixtures` | Partite giocate |
| `list_played_fixtures_with_predictions` | Giocate + predizione |
| `get_next_fixtures_with_predictions` | Merge upcoming/played + predizioni (paginato) |
| `compute_daily_prediction_stats` | Metriche per giorno |
| `compute_prediction_summary` | Summary + breakdown per modello |

#### `app/services/published_predictions.py`

Registro append-only dei pronostici **pubblicati** (non sostituisce `MatchPrediction` né le schedine).

| Funzione | Ruolo |
|----------|-------|
| `publish_prediction` | Inserisce snapshot v1 + `content_hash` (rifiuta se partita già iniziata) |
| `correct_published_prediction` | Nuova versione collegata a `previous_version_id` (solo su latest; freeze post-kickoff) |
| `list_published_predictions` / `get_published_prediction` | Storico e dettaglio |
| `list_publication_versions` | Catena versioni per `publication_id` |
| `compute_content_hash` / `match_has_started` | Hash canonico SHA-256; freeze su kickoff UTC / stato terminale |

#### `app/services/live_betting_metrics.py`

Formule pure per il tipbook live (separate da `ml.training.value_bet_metrics`):

| Funzione | Ruolo |
|----------|-------|
| `hit_rate` / `hit_rate_pct` | won / (won + lost); void/open esclusi |
| `roi_pct` / `yield_pct` | profit / stake_settled × 100 (identici per convenzione prodotto) |
| `max_drawdown` | Max calo peak→trough sulla curva equity dei tip chiusi in ordine cronologico |
| `longest_streaks` | Serie positiva/negativa max (void/open saltati) |

#### `app/services/published_live_stats.py`

KPI live **solo** dal ledger `PublishedPrediction` (non da `MatchPrediction` / schedine / backtest). Settlement a lettura via `match_lifecycle.settle_simulated_bet`.

| Funzione | Ruolo |
|----------|-------|
| `compute_published_live_stats` | Totale/chiusi/aperti/void, hit rate, stake, profitto, ROI, yield, quota media, max drawdown, streak, distribuzioni; filtri `tournament_name` / `surface` / `odds_band` |
| `settle_published_tips` / `list_settled_published_tips` | Settlement a lettura + liste tip con esito |
| `selection_to_predicted_winner` | Mappa selection (nome/lato) → First/Second Player |
| `odds_bucket` / `edge_bucket` / `period_key` | Bucket per distribuzioni |

#### `app/services/live_beta_dashboard.py`

Aggregato admin per la beta live: riusa pipeline (`global_update` + `import_state`), tipbook live, telegram stats, completezza quote/snapshot ed errori recenti. Non mescola training/backtest nei KPI LIVE.

| Funzione | Ruolo |
|----------|-------|
| `compute_live_beta_dashboard` | Risposta unica per `GET /api/live-beta-dashboard` (include `publication_health` diagnostico e copertura closing) |

#### `app/services/weekly_beta_report.py`

Report settimanale beta (settimana ISO lun–dom, fuso Europe/Rome): utenti totali/attivi/nuovi, retention W1, utilizzo comandi, tip pubblicati + ROI/yield/drawdown live, errori pipeline, notifiche fallite, feedback, confronto settimana precedente. Persistenza in `weekly_beta_report`; riepilogo admin via `send_admin_alert`.

| Funzione | Ruolo |
|----------|-------|
| `compute_weekly_beta_report_payload` | Aggrega KPI settimana corrente + precedente + delta WoW |
| `generate_and_store_weekly_beta_report` | Upsert DB + invio Telegram admin opzionale |
| `format_admin_telegram_summary` | Testo riepilogo per `TELEGRAM_ADMIN_CHAT_ID` |
| `list_weekly_beta_reports` / `get_latest_weekly_beta_report` | Lettura storico |

Job: `python -m backend.src.jobs.run_weekly_beta_report` (`docs/SCHEDULING.md`). Flag: `WEEKLY_BETA_REPORT_TELEGRAM_ENABLED` (usa `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ADMIN_CHAT_ID`, indipendente da `OPS_ALERTS_ENABLED`).

#### `app/services/live_publication_service.py`

Pubblica nel registro immutabile solo le giocate ufficiali **PLAY** della combo pubblica (env), riusando `build_candidate_pool` e `publish_prediction`. Idempotente su `(event_key, selection, model_version, model_name, publication_source)` per `content_version=1`.

| Funzione | Ruolo |
|---|---|
| `resolve_public_model_config` | Valida `LIVE_PUBLICATION_ENABLED` / `PUBLIC_MODEL_*` senza fallback silenzioso |
| `publish_official_plays_for_day` | Filtra PLAY → `PublishedPrediction` + snapshot `publication` |
| `find_existing_live_publication` | Dedup pre-insert |

Convenzione bookmaker snapshot di pubblicazione senza book reale: `publication`.

#### `app/services/prematch_odds_snapshots.py` (closing)

| Funzione | Ruolo |
|---|---|
| `seal_closing_from_last_prematch` | Etichetta come `closing` l’ultimo opening/observed pre-kickoff (non inventa quote) |
| `record_odds_payload` | Se `event_live` → non scrive observed post-inizio; tenta seal closing |

**Formule e convenzioni (tipbook live):**

- **Open** = pending; **Void** = stake restituito (escluso da hit rate / ROI / yield); **Closed** = won ∪ lost.
- **Hit rate** = won / (won + lost).
- **Stake totale** = Σ `unit_stake` su tutta la popolazione filtrata.
- **Stake settled** = Σ stake realizzati su won+lost (denominatore ROI/yield).
- **Profitto** = Σ P/L (won: stake×(odds−1); lost: −stake; void/open: 0).
- **ROI %** = **Yield %** = profit / stake_settled × 100 (`null` se stake settled = 0).
- **Quota media** = media aritmetica delle odds pubblicate presenti.
- **Max drawdown** = massimo calo peak→trough sulla equity cumulata dei soli tip chiusi (ordine `event_date`, `published_at`).
- **Serie +/-** = run consecutive di won / lost nella stessa sequenza (void/open saltati, non interrompono).
- Default: `latest_only=true` (una riga per `publication_id`).
- Separato da training/backtest (`value_bet_metrics`) e dalle stats operative su `MatchPrediction` / `BettingSlip*`.

#### `app/services/prematch_odds_snapshots.py`

Ledger append-only delle quote pre-match (non sostituisce il JSON su `Fixture`/`NextFixture`, né la tabella ML `odds_snapshot`).

| Funzione | Ruolo |
|----------|-------|
| `record_snapshot` | Append singolo rilevamento (dedup per `detection_hash` / quote invariate) |
| `record_odds_payload` | Parse matrice Home/Away → N snapshot (tipo `auto` → opening/observed) |
| `record_odds_from_stored_fixture` | Cattura da odds JSON di `NextFixture`/`Fixture` |
| `list_snapshots` / `get_snapshot` | Storico e dettaglio |
| `capture_imported_odds` | Hook best-effort usato da `import_next_fixtures` |
| `compute_detection_hash` / `resolve_snapshot_type` | Fingerprint dedup; apertura vs osservazione |

#### `app/services/betting_slips.py`

| Simbolo | Ruolo |
|---------|-------|
| `CandidatePick` / `GeneratedSlip` | Dataclass candidate / slip generata |
| `SLIP_PROFILES` | 9 profili: 3 Play, 3 Play+Borderline, 3 miste (tutti gli stati) |
| `build_candidate_pool` | Pool pick da fixtures+predizioni+odds (include PLAY/BORDERLINE/NO BET) |
| `generate_slips` | Seleziona pick per tier di difficoltà e costruisce slip |
| `get_betting_slip_calendar` | Giorni con presenza/assenza slip |
| `get_daily_betting_slips` | Legge o genera slip del giorno con `min_edge_percent` globale |
| `refresh_betting_slips` | Rigenera forzando delete/upsert |
| `compute_betting_slip_stats` | ROI/winrate per profilo e giorno (profitto su `effective_combined_odds`) |
| `compute_betting_slip_model_stats` | Stats aggregate per versione/modello |
| `_resolve_pick_status` / `_resolve_slip_status` | Settlement on-read: `pending`/`won`/`lost`/`void`; void ignorati per win; slip tutta void → `void` |
| `effective_combined_odds` | Prodotto quote dei soli pick non-void (quota originale resta in `combined_odds`) |

#### `app/services/match_lifecycle.py`

| Simbolo | Ruolo |
|---------|-------|
| `classify_match_lifecycle` | Normalizza `event_status`/winner → `upcoming`/`started`/`completed`/`postponed`/`cancelled`/`abandoned`/`walkover`/`retired`/`unknown` (alias legacy: `scheduled`/`live`/`finished`/`unknown_problem`) |
| `settlement_policy` / `settle_simulated_bet` | Matrice esplicita effetti su singole/schedine/stake/profitto/ROI; idempotente; cancelled/non disputate → void (mai perse) |
| `is_void_for_betting` | Pick void se status terminale senza winner bettable; postponed resta pending |
| `match_lifecycle_label` | Label IT per UI/Telegram |
| `resolve_slip_status_from_picks` / `slip_profit_units` | Aggregazione slip e P/L (void/pending → 0) |

**Nota naming:** `void_odds` = quota void/break-even del modello (`1/P`). Non confondere con `pick_status="void"` (partita annullata / non scommettibile).

#### `app/services/single_match_value.py`

| Funzione | Ruolo |
|----------|-------|
| `calculate_void_odds` | Quota void / break-even data P(modello) |
| `calculate_match_min_edge_percent` | Helper overround (opzionale); il default operativo è `DEFAULT_MIN_EDGE_PERCENT = 2` |
| `calculate_expected_roi` | ROI atteso quota vs probabilità |
| `classify_single_bet_value` | `PLAY` / `NO BET` / `BORDERLINE` rispetto a void + margine |
| `analyze_single_match_value` | Analisi singola partita (suggested + effective min edge) |
| `get_single_match_value_analysis` | Entry point usato dalla route |

#### `app/services/global_update.py`

| Simbolo | Ruolo |
|---------|-------|
| `ModelCombination` | Coppia `(model_version, model_name)` |
| `list_enabled_combinations` | Combo con artefatto `.pkl` su disco |
| `reconcile_orphaned_runs` | Marca run zombie come `interrupted` (riprendibili) |
| `start_global_update` | Crea/riprende run; thread API o `blocking=True` per CLI |
| `cancel_global_update` | Cancel cooperativa (flag DB + lock-aware) |
| `_execute_global_update` | Lock → import → next → predict/slip/live → sync opz. → report |
| `exit_code_for_run` | Exit code per cron/worker |
| `build_run_report` | Report strutturato della run |
| `get_models_versions_results` | Esito per modello/versione su una data |
| `get_run_by_id` / `get_latest_run` / `get_active_run` / `get_resumable_run` | Lettura stato |

#### `app/services/pipeline_lock.py`

Lock distribuito su tabella `pipeline_lock` (`acquire` / `heartbeat` / `release`).

#### `app/services/imports.py` / `import_state.py`

Gestione refresh upcoming, purge fixture incomplete future, stato ultimo import su file/DB.

#### `app/services/telegram_analytics.py`

| Funzione | Ruolo |
|----------|-------|
| `record_telegram_event` | Insert evento in `telegram_bot_event` |
| `record_telegram_event_safe` | Come sopra ma non solleva (usato dal bot) |
| `list_telegram_events` | Lista paginata/filtrata per admin API |
| `compute_telegram_stats` | KPI: totali, utenti unici, top action, by_action, by_day |

Schema Pydantic: `app/schemas/telegram_analytics.py` (`TelegramBotEventRead`, `TelegramBotEventsResponse`, `TelegramBotStatsResponse`, …).

#### `app/services/telegram_users.py`

Registro utenti beta Telegram (whitelist). Non sostituisce `TelegramBotEvent` (analytics).

| Funzione | Ruolo |
|----------|-------|
| `register_or_touch_on_start` / `_safe` | Upsert al `/start` (id, `chat_id`, username, nome, primo/ultimo accesso, origine invito) |
| `check_telegram_access` / `_safe` | Controllo accesso centralizzato (whitelist + termini) |
| `accept_telegram_terms` / `_safe` | Accettazione condizioni (versione da settings) |
| `update_notification_preferences` / `_safe` | Preferenze push (`/notifiche`) |
| `invite_telegram_user` | Pre-registrazione admin (status tipicamente `invited`) |
| `list_telegram_users` | Ricerca/filtri admin |
| `activate_telegram_user` / `suspend_telegram_user` / `block_telegram_user` | Transizioni stato |

Schema: `app/schemas/telegram_users.py`. Route admin: `app/api/routes/telegram_users.py`. Gate bot: `app/telegram/access.require_beta_access`.

Settings: `telegram_whitelist_enabled` (default true), `telegram_terms_required` (default false), `telegram_terms_version`.

#### `app/services/telegram_feedback.py`

Inbox feedback dal comando bot `/feedback`. Persistenza solo al submit finale (niente bozze/conversazioni intermedie).

| Funzione | Ruolo |
|----------|-------|
| `create_telegram_feedback` / `_safe` | Crea feedback (`new`) da bot |
| `list_telegram_feedback` | Ricerca/filtri admin (stato, categoria, utente, testo) |
| `get_telegram_feedback` | Dettaglio per id |
| `update_telegram_feedback_status` | Transizioni `new` → `reviewing` → `resolved`/`rejected` |

Schema: `app/schemas/telegram_feedback.py`. Route admin: `app/api/routes/telegram_feedback.py`. Categorie: `bug`/`content`/`ux`/`feature`/`access`/`other`.

#### `app/services/telegram_notifications.py`

Push configurabili verso utenti beta (separati dagli alert admin in `observability/alerts.py`).

| Funzione | Ruolo |
|----------|-------|
| `list_notification_recipients` | Destinatari `active` + preferenze + `chat_id` + termini; esclude sospesi |
| `build_predictions_message` / `build_results_message` / `build_empty_day_message` | Contenuti testuali |
| `deliver_to_user` | Bot API con dedupe DB, retry 429/5xx, log errore |
| `run_notification_kind` / `run_daily_telegram_notifications` | Orchestrazione `predictions` / `results` / `empty_day` |

Job: `python -m backend.src.jobs.run_telegram_notifications` (`docs/SCHEDULING.md`). Master: `TELEGRAM_NOTIFICATIONS_ENABLED` (default false).

---

### 4.5 ML — dataset, training, predizione

#### `app/ml/model_versioning.py`

| Simbolo | Ruolo |
|---------|-------|
| `ModelVersion` | `"v1" \| "v2" \| "v3"` |
| `DatasetVersionPaths` / `ModelVersionPaths` | Path dataset/modelli/metriche per versione |
| `DATASET_VERSIONS` / `MODEL_VERSIONS` | Registry path |
| `dataset_candidates` | Lista CSV candidati per training |
| `select_training_dataset_path` | Sceglie il CSV di training |

#### `app/ml/model_selection.py`

`select_best_model(version)` — sceglie il modello con miglior `roc_auc` (fallback accuracy / log_loss) dalle metriche JSON.

#### `app/ml/datasets/dataset_builder.py`

| Simbolo | Ruolo |
|---------|-------|
| `load_legacy_match_rows` | Legge `fixture`+`tournament` dal DB |
| `legacy_match_rows_to_dataframe` / `_v2` | Feature storiche (forma, H2H, Elo, rank) |
| `build_dataset_dataframe` / `_v2` | Pipeline completa DataFrame |
| `clean_dataset_dataframe` / `_v2` | Normalizza missing (rank 9999, Elo 1500, …) |
| `split_features_target` | Separa X/y |
| `export_dataset_csv` | Scrive CSV |
| `build_and_export_dataset*` / `*_report*` / `*_v2` | Entry point build+export+summary |

#### `app/ml/datasets/elo_builder.py` — `EloTracker`

| Metodo | Ruolo |
|--------|-------|
| `pre_match_features` | Elo overall/surface **prima** del match |
| `record_match` | Aggiorna Elo dopo il risultato |
| `get_overall` / `get_surface` | Lettura rating |

Funzioni: `expected_score`, `update_elo`.

#### `app/ml/datasets/ranking_history.py`

`HistoricalRankingLookup` — rank/points ATP storici pre-match; `build_historical_ranking_lookup`.

#### `app/ml/datasets/odds_builder.py`

Parsing quote match-winner, aggregati bookmaker, attach a dataset:

`load_fixture_odds_records`, `aggregate_match_odds`, `attach_odds_to_dataset`, `build_and_export_odds_dataset`, utilità `implied_probability`, `bookmaker_margin`, `no_vig_market_probabilities`, ROI/hit-rate.

#### `app/ml/datasets/atp_singles_enrichment.py`

Matching fixture ↔ CSV ATP singles: `build_atp_singles_outputs`, mapping player/match, export dataset arricchito.

#### CLI dataset

- `python -m app.ml.datasets.build_dataset [--version v2|v3]`
- `python -m app.ml.datasets.build_atp_singles [--version …]`
- `python -m app.ml.datasets.build_odds_dataset [--version …]`  
  (da `backend/src`)

#### `app/ml/features/feature_builder.py`

Feature engineering su tabelle `ml_*` / snapshot: win-rate, H2H, giorni dall’ultimo match, `build_feature_snapshots`, `prepare_feature_snapshot_row`.

#### `app/ml/training/train_baseline.py`

| Funzione | Ruolo |
|----------|-------|
| `temporal_train_test_split` | Split temporale (no shuffle random) |
| `allowed_feature_columns` / `leakage_excluded_columns` | Feature ammesse per versione |
| `filter_rows_with_valid_odds` | Filtro obbligatorio per v3 |
| `train_baseline` | Allena LR + RF, salva `.pkl` e metriche |
| `classification_metrics` | accuracy, ROC-AUC, log-loss, … |
| `market_benchmark_metrics` | Benchmark mercato sulle odds |
| `compute_value_bet_metrics` (modulo dedicato) | Metriche value bet |
| `update_model_registry_entry` / `write_model_comparison` | Registry JSON |

#### `app/ml/training/walk_forward.py`

Validazione temporale multi-fold **separata** dalla holdout di `train_baseline` e dalle metriche live.

| Funzione | Ruolo |
|----------|-------|
| `WalkForwardConfig` | Finestra iniziale, test/step days, mode expanding/rolling, embargo, min rows |
| `generate_walk_forward_folds` | Genera fold ordinati cronologicamente (train → test immediatamente successivo) |
| `prepare_temporal_dataframe` | Ordina per data, nessun shuffle |
| `evaluate_fold_models` | Training in-memory per fold (non scrive `.pkl` di produzione) |
| `run_walk_forward_validation` | Esegue tutte le versioni; confronta holdout senza sovrascriverlo |
| `write_walk_forward_report` | JSON sotto `data/reports/walk_forward/` |

Persistenza: entity `WalkForwardRun` / `WalkForwardFold` (migrazione `0021`), service `app/services/walk_forward.py`, job `jobs/run_walk_forward.py`. Il global update include una fase osservabile `walk_forward_observe` (esecuzione completa solo se `WALK_FORWARD_IN_GLOBAL_UPDATE=true`).

#### `app/ml/training/calibration.py`

| Funzione | Ruolo |
|----------|-------|
| `CalibrationConfig` | Bin reliability, min campioni, metodi (raw/platt/isotonic), finestra walk-forward |
| `compute_calibration_metrics` | Brier, log loss, ECE, MCE, reliability bins per fascia |
| `fit_calibrator` / `apply_calibrator` | Platt scaling (LogisticRegression) e isotonic regression |
| `collect_oos_predictions_for_version` | Rigenera probabilità OOS per fold walk-forward |
| `evaluate_fold_calibration` | Addestra calibratore solo su OOS passato, valuta fold corrente |
| `run_calibration_validation` | Orchestrazione multi-versione; salva artefatti versionati |
| `write_calibration_report` | JSON sotto `data/reports/calibration/` (+ `calibration_latest.json`) |

Persistenza: entity `CalibrationRun` / `CalibrationResult` (migrazione `0022`), service `app/services/calibration.py`, job `jobs/run_calibration.py`, UI `CalibrationPage`. Pickle calibratori in `data/models/v{N}/calibrators/calibration_run_{id}_{model}_{method}.pkl` (non sovrascrive run precedenti). **Non** attiva automaticamente la calibrazione sul modello pubblico.

#### `app/ml/prediction/predictor.py`

| Simbolo | Ruolo |
|---------|-------|
| `PreMatchFeatureBuilder.from_db` | Carica storico e costruisce stato forma/Elo/H2H |
| `PreMatchFeatureBuilder.build_feature_row` | Feature pre-match per una fixture |
| `odds_feature_row` | Feature odds per v3 |
| `predict_fixture` | Inferenza singola → probabilità |
| `predict_upcoming_fixtures` | Batch su next fixtures, persistenza `MatchPrediction` |
| `clear_model_cache` | Svuota cache artefatti in memoria |
| `PredictUpcomingCancelled` | Cancel cooperativa durante predict |

---

### 4.6 Import e sync

#### `service/import_fixtures.py`

`import_all_fixtures`, `run_daily_fixture_import` — scarica/upsert partite per range date.

#### `service/import_next_fixtures.py`

| Funzione | Ruolo |
|----------|-------|
| `import_next_fixtures` | Import finestra giorni forward |
| `run_daily_next_fixture_import` | Daily: upcoming + promozione completati |
| `upsert_next_fixture` / `upsert_fixture_from_api` | Upsert |
| `promote_completed_match` | Sposta in `fixture` e risolve predizioni |
| `resolve_predictions_for_match` | Set `actual_winner` sulle predizioni |
| `fetch_odds_for_match` | Odds per event_key |

#### `service/import_stading_player.py` / `basic_import.py`

Import classifiche/giocatori e bootstrap eventi/tornei.

#### `service/database_migrator.py`

`run_migration(upsert=…, tables=…)` — copia tabelle SOURCE → TARGET con upsert sulle PK di conflitto.

#### `utility/request_api.py`

Client HTTP verso API tennis (chiavi da `config.env`).  
Timeout esplicito (`API_TENNIS_TIMEOUT`, default 30s). Errori tipizzati: timeout, rete, HTTP, risposta non valida.  
I log non contengono credenziali: URL/query/params vengono sanificati via `utility/sensitive_data.py` (APIkey, token, password, Authorization, Cookie, …). Il dict `params` del chiamante non viene mutato.

#### `utility/sensitive_data.py`

Sanitizzazione centralizzata per log: `sanitize_url`, `sanitize_headers`, `sanitize_payload`, `sanitize_text`.

---

### 4.7 Jobs

#### `jobs/run_ops_checks.py`

Controlli operativi post-job (`import_freshness`, `predictions_present`, `pipeline_duration`, `latest_run_outcome`); `--alert` invia Telegram/webhook. Exit `0/1/2`. Vedi [MONITORING.md](docs/MONITORING.md).

#### `jobs/run_db_backup.py` / `jobs/run_db_restore.py`

Backup logico PostgreSQL (`pg_dump` custom + SHA-256, retention, GPG opzionale) e restore a tre modalità: `dry-run`, `test` (DB alternativo), `overwrite` (guardato). Helper: `service/postgres_backup.py`. Wrapper cron: `scripts/backup_postgres.sh|.bat`, `scripts/restore_postgres.sh|.bat`. Guida DR: [BACKUP_DR.md](docs/BACKUP_DR.md).

#### `jobs/run_global_update.py` (produzione)

CLI blocking sullo stesso orchestratore UI/API: lock DB, retry/timeout, resume, report, exit code.
Opzioni: `--force`, `--resume`, `--sync-cloud`, `--no-auto-resume`.

#### `jobs/daily_pipeline.py` — `DailyPipeline`

Wrapper di compatibilità: delega a `run_global_update` (tutte le combo abilitate + sync opzionale).

#### `jobs/generate_upcoming_predictions.py`

`run_upcoming_prediction_generation` — seleziona modello (best metrics o nome esplicito) e chiama `predict_upcoming_fixtures`. Utile per run mirate; il job giornaliero di produzione usa l’orchestratore globale.

---

## 5. Frontend — riferimento moduli

### Routing (`App.tsx`)

| Path | Pagina |
|------|--------|
| `/login` | `LoginPage` (pubblica) |
| `/` | Redirect → `/predictions` (protetta) |
| `/live-beta-dashboard` | `LiveBetaDashboardPage` |
| `/predictions` | `PredictionsPage` |
| `/prediction-stats` | `PredictionStatsPage` |
| `/published-predictions` | `PublishedPredictionsPage` |
| `/published-live-stats` | `PublishedLiveStatsPage` |
| `/betting-slips` | `BettingSlipsPage` |
| `/betting-slip-model-stats` | `BettingSlipModelStatsPage` |
| `/global-update-report` | `GlobalUpdateReportPage` |
| `/telegram-bot` | `TelegramBotPage` |
| `/telegram-users` | `TelegramUsersPage` |
| `/telegram-feedback` | `TelegramFeedbackPage` |
| `/weekly-beta-report` | `WeeklyBetaReportPage` |
| `/walk-forward` | `WalkForwardPage` |
| `/calibration` | `CalibrationPage` |

Wrapper: `AuthProvider` → route protette con `ProtectedRoute` → `GlobalUpdateProvider` + `Layout`.  
L’albero route è esportato come `appRoutes` (runtime: `createBrowserRouter`; test: `createMemoryRouter`).

### Pagine

| Componente | Ruolo |
|------------|-------|
| `LoginPage` | Login admin; salva access token in `localStorage` |
| `LiveBetaDashboardPage` | Dashboard admin beta live: pipeline, tip oggi/aperti/chiusi, KPI+drawdown, bot, errori, completezza; separazione LIVE/BACKTEST |
| `PredictionsPage` | Lista partite+predizioni; margine globale (default 2%); void/decision in riga |
| `PredictionStatsPage` | Summary e serie giornaliere accuracy/ROI |
| `PublishedPredictionsPage` | Storico registro immutabile pubblicazioni (filtri, versioni, hash) |
| `PublishedLiveStatsPage` | KPI live tipbook dal ledger (hit rate, ROI/yield, drawdown, streak, distribuzioni) |
| `BettingSlipsPage` | Calendario, tab modello, 9 slip a tier, colonna media quote bookmakers, margine globale (default 2%), status pick void / quota effettiva |
| `BettingSlipModelStatsPage` | Tabella comparativa stats per modello |
| `GlobalUpdateReportPage` | Report ultima run globale: errori, warning, fasi, combo |
| `TelegramBotPage` | Analytics admin bot: KPI, filtri data/action/user, breakdown per giorno, storico eventi |
| `TelegramUsersPage` | Gestione utenti beta: ricerca, invito, attiva/sospendi/blocca, termini e origine invito |
| `TelegramFeedbackPage` | Inbox feedback bot: filtri stato/categoria, messaggio, transizioni `new`/`reviewing`/`resolved`/`rejected` |
| `WeeklyBetaReportPage` | Report settimanale beta salvati: KPI utenti/retention/comandi/tip/ROI/pipeline/notifiche/feedback + WoW; generazione manuale |
| `WalkForwardPage` | Validazione walk-forward: fold, metriche, copertura, fold saltati e flag leakage; avvio manuale (non aggiorna modello pubblico) |
| `CalibrationPage` | Calibrazione probabilità OOS: grezzo vs Platt/isotonic, ECE/MCE/Brier/log loss, reliability curve e tabella fasce (campione insufficiente evidenziato); non attiva modello pubblico |

### Componenti / hook

| Modulo | Ruolo |
|--------|-------|
| `ProtectedRoute` | Redirect a `/login` se non autenticato |
| `Layout` | Sidebar, nav, logout, slot `GlobalUpdateControls` |
| `GlobalUpdateControls` | Start/cancel/status aggiornamento globale; link a report se ci sono errori |
| `ModelControls` | Selettore versione/nome modello |
| `Status` | `LoadingState` / `ErrorState` / `EmptyState` |
| `MetricCard` | Card metrica |
| `useGlobalUpdate` | Context: polling status, start/cancel |
| `auth/AuthContext` | Sessione admin, login/logout, restore da token |

### `services/apiClient.ts`

Client `fetch` tipizzato verso le API montate: auth (`login` / `getSession` / `logout`), predictions, published-predictions (+ live stats), live-beta-dashboard, weekly-beta-reports, walk-forward, calibration, betting-slips, imports, global-update, single-match-value, Telegram analytics / users / feedback.
Invia `Authorization: Bearer` quando presente; su **401** notifica il handler di sessione scaduta.  
`ApiError` — errore HTTP con `status`.

### Utils

- `utils/modelVersion.ts` — default UI `v3`, persistenza localStorage; `resolvePreferredModelVersion` su Predictions / Betting slips / Stats
- `utils/minEdge.ts` — classificazione PLAY/BORDERLINE/NO BET lato client
- `utils/tennis.ts` — format date/score/superficie/nomi giocatore
- `types/api.ts` — tipi TypeScript allineati agli schema Pydantic (incl. tipi Telegram analytics)

---

## 6. Pipeline ML

### Versioni

| Versione | Idea | Odds in training/inferenza |
|----------|------|----------------------------|
| **v1** | Baseline forma/H2H/ATP parziale | No (solo post-hoc edge) |
| **v2** | Rank storico, Elo, forma, H2H, ATP | No (solo post-hoc) |
| **v3** | Feature v2 + aggregati quote pre-match | Sì (solo match con odds) |

Default:

| Contesto | Versione |
|----------|----------|
| UI frontend (`DEFAULT_MODEL_VERSION`) | **v3** |
| Bot Telegram (`TELEGRAM_MODEL_VERSION`) | **v3** |
| Query param API REST (se omesso) | **v2** |
| Job `run_global_update` (tutte le combo abilitate) | artefatti su disco |
| `generate_upcoming_predictions` (run mirata) | **v2** |

Modelli tipici: `logistic_regression`, `random_forest`.

### Comandi tipici (da `backend/src`)

```bash
python -m app.ml.datasets.build_dataset --version v3
python -m app.ml.datasets.build_atp_singles --version v3
python -m app.ml.datasets.build_odds_dataset --version v3
python -m app.ml.training.train_baseline --model-version v3
# dalla root: walk-forward (non sovrascrive baseline_* né il modello pubblico)
python -m backend.src.jobs.run_walk_forward --dry-run

# calibrazione probabilità OOS (dipende da walk-forward; non attiva modello pubblico)
python -m backend.src.jobs.run_calibration --dry-run
python -m backend.src.jobs.run_calibration
python -m jobs.generate_upcoming_predictions --model-version v3
```

Artefatti:

- Dataset: `backend/data/processed/`
- Modelli: `backend/data/models/` (`v2/`, `v3/`, …)
- Metriche holdout: `backend/data/reports/baseline_*_metrics.json`
- Metriche walk-forward: `backend/data/reports/walk_forward/` (DB: `walk_forward_run` / `walk_forward_fold`)
- Calibrazione probabilità: `backend/data/reports/calibration/` (DB: `calibration_run` / `calibration_result`)

**Anti-leakage**: feature solo con dati *precedenti* al match; `standing` corrente non usata come rank pre-match; split temporale in training; walk-forward ufficiale senza shuffle e senza sovrapposizione train/test.

---

## 7. Import, job e sync

```bash
# dalla root del repository (vedi SCHEDULING.md)
python -m backend.src.service.import_fixtures
python -m backend.src.jobs.run_global_update --days-forward 10
python -m backend.src.jobs.run_global_update --force --sync-cloud
python -m backend.src.jobs.run_global_update --resume
```

Dettagli cron Windows/Linux, lock/resume/exit code e sync cloud: [docs/SCHEDULING.md](docs/SCHEDULING.md).

---

## 8. Bot Telegram

Modulo `app/telegram/`.

| Modulo | Ruolo |
|--------|-------|
| `config.TelegramSettings` | Token, `TELEGRAM_API_BASE_URL`, `telegram_service_api_key` (S2S, allineata a `SERVICE_API_KEY`), model version/name, `telegram_model_names` (fallback multi-modello), stake, `telegram_slip_count` (default 9), `telegram_min_edge_percent` (default 2.0), whitelist/termini (`telegram_whitelist_enabled`, `telegram_terms_required`, `telegram_terms_version`), `telegram_feedback_url` (link pubblico opzionale in footer) |
| `client.BackendApiClient` | Chiama le stesse API FastAPI (`/betting-slips/daily`, `/betting-slips/stats/by-model`, `/predictions/stats/summary`, `/models-versions/results`, `/next-fixtures/predictions`, `/single-match-value`, …) |
| `bot.build_application` / `main` | Polling + handler comandi |
| `rate_limit.rate_limited` | Limite comandi per `telegram_user_id` (DB condiviso; messaggio IT se superato) |
| `access.require_beta_access` | Gate centralizzato whitelist + termini su comandi privilegiati |
| `tracking.tracked` / `track_callback_query` | Persistenza accessi/click in `telegram_bot_event` (non blocca il bot se il DB fallisce) |
| `fixture_value.enrich_fixture_value` | Void/valore su `/partite` (SMVA o fallback da probabilità modello) |
| `messages` / `dates` / `images` / `slips_compare` / `public_labels` | Formattazione risposte, date Roma, PNG, confronto multi-serie, etichette pubbliche (accuratezza) |

Service condivisi: `app/services/telegram_analytics.py`, `app/services/telegram_users.py`, `app/services/telegram_feedback.py`, `app/services/telegram_notifications.py` (vedi §4.4).

**Comandi attivi:** `/start`, `/help`, `/accetta_condizioni`, `/notifiche`, `/feedback`, `/annulla` (solo durante feedback), `/schedine`, `/partite`, `/statistiche`.

`/start` registra (o aggiorna) l’utente in `telegram_user` con `telegram_user_id`, `chat_id`, username, nome, primo/ultimo accesso, stato, origine invito (payload deep-link), preferenze notifiche e stato termini, poi mostra menu inline (Partite / Schedine / Statistiche / Aiuto). `/help` è una guida sintetica con la stessa tastiera. `/notifiche` mostra o aggiorna le preferenze push (master, pronostici, risultati, giorno vuoto). `/feedback` avvia una conversazione a step (categoria → valutazione 1–5 → messaggio) con annullo via `/annulla` o pulsante; salva solo il submit finale in `telegram_feedback` (stato iniziale `new`). Con whitelist attiva (default) i nuovi utenti restano `invited` finché un admin non li attiva dalla pagina **Utenti beta Telegram**. `/schedine`, `/partite`, `/statistiche` (e i relativi pulsanti menu) richiedono accesso centralizzato (`active` + termini se `TELEGRAM_TERMS_REQUIRED=true`); `/feedback` resta disponibile senza gate beta (utile anche per segnalazioni di accesso).

Push automatiche (job dedicato, default disabilitato): pronostici del giorno, riepilogo risultati, giorno senza partite; dedupe/retry/ledger in `telegram_notification_delivery`. Alert admin pipeline fallita restano su `OPS_ALERTS_*` / `TELEGRAM_ADMIN_CHAT_ID`.

UX pubblica: messaggi di caricamento sulle operazioni costose, footer uniforme con ultimo aggiornamento (da `GET /models-versions/results` → `last_updated_at`), avvertenza informativa e opzionale `TELEGRAM_FEEDBACK_URL`, errori centralizzati (`format_user_error`), stati vuoti espliciti per partite/schedine/statistiche. Nomi tecnici (`v3`, `logistic_regression`, `random_forest`) restano interni; all’utente solo etichette pubbliche.

Ogni comando/callback menu (e i messaggi non gestiti) viene registrato in tabella `telegram_bot_event`; gli step intermedi di `/feedback` non vengono tracciati come eventi dedicati (solo l’entry `/feedback`). Analytics (`/telegram-bot`), gestione utenti (`/telegram-users`) e inbox feedback (`/telegram-feedback`) sono solo dashboard admin.

`/schedine` carica le schedine di tutti i modelli della versione configurata. Se i contenuti coincidono (stessi match e stessi vincitori previsti) ne mostra una sola serie; se differiscono anche solo per una partita/pick, mostra entrambe con etichetta pubblica basata sull’accuratezza (es. `Serie A · accuratezza 58.2%`). L’intro include data, legende stati/valore, ultimo aggiornamento e disclaimer. Pick void escludono la quota dalla combinata effettiva.

`/partite` allinea la pagina **Partite**: tabella Ora/Torneo/Surface/Match/Predetto/Conf./Void/Valore/Stato (stato partita normalizzato), void+valore via SMVA (fallback da probabilità modello), multi-serie se i predittori differiscono (stesse etichette pubbliche), intro coerente con legende + ultimo aggiornamento. Senza partite risponde con messaggio dedicato (non un fallimento generico).

`/statistiche` mostra PNG di confronto (partite + schedine con profitto/ROI) usando le stesse etichette pubbliche. Comandi pronostici (`/pronostici`, `/giorno`, `/10giorni`, `/cerca`) restano nel codice ma non sono registrati.

```bash
cd backend
python -m src.app.telegram.bot
```

---

## 9. Schema dati

Tabelle legacy import: `fixture`, `player`, `tournament`, `event`, `standing`, `next_fixture`, `match_prediction`, tabelle betting slip (`betting_slip`, `betting_slip_day`, `betting_slip_pick`) e global update (`global_update_run`, `global_update_run_item`), `pipeline_lock` (lock distribuito job; migrazione `0016`), `telegram_bot_event` (analytics accessi bot), `telegram_user` (utenti beta / whitelist; migrazione `0017`, prefs/`chat_id` in `0018`), `telegram_notification_delivery` (ledger push; migrazione `0018`), `telegram_feedback` (feedback in-bot; migrazione `0019`), `weekly_beta_report` (report settimanale beta; migrazione `0020`), `walk_forward_run` / `walk_forward_fold` (validazione temporale walk-forward; migrazione `0021`), `calibration_run` / `calibration_result` (analisi calibrazione OOS; migrazione `0022`), `published_prediction` (registro immutabile pubblicazioni; migrazione `0013`), `prematch_odds_snapshot` (storico quote pre-match append-only; migrazione `0014`).

Tabelle ML canoniche (migrazioni Alembic): `ml_player`, `ml_tournament`, `ml_match`, `ranking_snapshot`, `odds_snapshot`, `feature_snapshot`.

Catena migrazioni recente (Alembic): `0010_telegram_bot_events` → `0011_admin_user` → `0012_rate_limit_bucket` → `0013_published_prediction` → `0014_prematch_odds_snapshot` → `0015_pp_live_idempotency` → `0016_pipeline_reliability` → `0017_telegram_user` → `0018_telegram_notifications` → `0019_telegram_feedback` → `0020_weekly_beta_report` → `0021_walk_forward` → `0022_calibration`.

```bash
cd backend
alembic upgrade head
```

---

## Test

### Backend

Da un ambiente pulito, dalla **root del repository**:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r backend/requirements-dev.txt
python -m pytest
```

Un solo comando esegue tutta la suite (`backend/tests`), con:

- database SQLite in-memory isolato (nessun PostgreSQL / `.env` reale richiesto);
- fixture condivise in `backend/tests/conftest.py` (`client`, `db_session`, `auth_headers`, …);
- override di `get_db` / settings FastAPI;
- blocco delle chiamate HTTP verso API-Tennis;
- report di copertura in terminale, `backend/htmlcov/` e `backend/coverage.xml`.

Configurazione: `pytest.ini` (root). Helper: `backend/tests/db_helpers.py`, `backend/tests/auth_helpers.py`.

Opzioni utili:

```bash
python -m pytest -q                          # output compatto
python -m pytest --no-cov                    # senza coverage
python -m pytest backend/tests/test_auth.py  # singolo modulo
```

Non sono necessari token Telegram, `API_TENNIS_KEY` o un database PostgreSQL per i test.

### Frontend

Da `frontend/` (dopo `npm ci`):

```bash
npm test                 # suite una tantum (Vitest + jsdom + RTL)
npm run test:watch       # modalità watch
npm run test:coverage    # coverage HTML/LCOV in frontend/coverage/
npm run build
```

La suite mocka `apiClient` / `fetch`: non serve un backend reale. Copertura tipica: avvio/navigazione, route admin protette, stati loading/errore/vuoto, aggiornamento globale, selettori versione/modello, pagine Partite / Schedine / Bot Telegram, errori HTTP del client API.

Configurazione: `frontend/vite.config.ts` (`test.environment = jsdom`, `setupFiles`), helper in `frontend/src/test/`.

---

## 10. CI (GitHub Actions)

Workflow: [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Parte su **push** e **pull request**.

| Job | Cosa fa |
|-----|---------|
| **Backend** | Python da `.python-version` (3.12), `pip install -r backend/requirements-dev.txt` (cache pip), PostgreSQL 16 di servizio, `alembic upgrade head`, `python -m pytest` |
| **Frontend** | Node da `frontend/.nvmrc` (22), `npm ci` (cache npm), `npm test`, `npm run build` |

- Credenziali solo fittizie (`ci-fake-*`, DB `tennis_oracle_ci` / user `postgres` / password `postgres`).
- I test backend restano su SQLite in-memory (`conftest.py`); Postgres in CI serve a validare le migrazioni Alembic.
- La pipeline fallisce se migrazioni, test o build falliscono.
- Cache dipendenze tramite `actions/setup-python` / `actions/setup-node` (hash di `requirements*.txt` e `package-lock.json`).

Stato: badge in cima a questo README, oppure [Actions → CI](https://github.com/romy1992/tennis_oracle/actions/workflows/ci.yml).

---

## 11. Docker

Vedi [docs/DOCKER.md](docs/DOCKER.md) per avvio/arresto, **hot-reload** (`docker-compose.dev.yml`), profili bot/job, rebuild prod-like e produzione.

| Artefatto | Contenuto |
|-----------|-----------|
| `backend/Dockerfile` | Multi-stage Python 3.12; default `uvicorn backend.src.app.main:app`; `HEALTHCHECK` su `/health` |
| `frontend/Dockerfile` | Multi-stage Node 22 build + `nginx:1.27-alpine`; build-arg `VITE_API_BASE_URL` |
| `docker-compose.yml` | Default: DB host (`host.docker.internal`); `migrate` + `api` + `frontend`; profili `bot` / `jobs` / `embedded-db` |
| `docker-compose.dev.yml` | Overlay hot-reload: mount `backend/src` + `frontend`, `uvicorn --reload`, Vite HMR |
| `docker-compose.prod.yml` | Overlay: no porta Postgres esposta (se usi embedded-db), `DEBUG=false`, log rotati |
| `docker-compose.staging.yml` | Overlay staging: progetto/volume/porte separati, `AUTO_MIGRATE`, CORS, `/ready` |
| `.env.example` | Modello env per Compose (copiare in `.env`) |
| `.env.staging.example` | Modello staging (copiare in `.env.staging`; vedi [STAGING.md](docs/STAGING.md)) |
| `backend/scripts/smoke_check.py` | Smoke HTTP su `/health`, `/ready`, frontend |
| `backend/scripts/run_alembic_upgrade.py` | Migrazioni Compose controllate da `AUTO_MIGRATE` |
| `backend/scripts/backup_postgres.sh|.bat` | Backup PostgreSQL pianificato (`run_db_backup --alert`) |
| `backend/scripts/restore_postgres.sh|.bat` | Restore (`dry-run` / `test` / `overwrite`) |

Test di regressione asset (senza demone Docker): `backend/tests/test_docker_assets.py`, `backend/tests/test_staging_assets.py`, `backend/tests/test_postgres_backup.py`. Backup/DR: [docs/BACKUP_DR.md](docs/BACKUP_DR.md).
