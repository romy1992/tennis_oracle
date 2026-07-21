# tennis_oracle — documentazione tecnica

Monorepo **backend FastAPI** (`backend/`) + **frontend React** (`frontend/`).

Il backend importa dati tennis da API esterna in PostgreSQL (`tennis_db`), espone API REST, genera previsioni ML, schedine e sincronizza opzionalmente verso un DB target.

| Documento | Pubblico |
|-----------|----------|
| **Questo file** | Sviluppatori: architettura, classi, metodi, API, ML |
| [docs/GUIDA_UTENTE.md](docs/GUIDA_UTENTE.md) | Utente medio: cosa fa il prodotto e come usarlo |
| [docs/SCHEDULING.md](docs/SCHEDULING.md) | Job giornaliero, cron, sync cloud |

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
                              jobs/daily_pipeline ──sync──► DB cloud (opz.)
```

**Layer backend (ordine tipico della richiesta):**

1. `api/routes/*` — endpoint HTTP
2. `app/services/*` — logica applicativa
3. `entity/*` + `app/models/*` — ORM SQLAlchemy
4. `repository/*` — CRUD legacy usato dagli import
5. `app/ml/*` — dataset, training, inferenza

---

## 2. Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env .env
alembic upgrade head
uvicorn src.app.main:app --reload
```

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
- `/health` (e docs OpenAPI) sono esclusi
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
```

`TELEGRAM_SERVICE_API_KEY` deve coincidere con `SERVICE_API_KEY` quando quest’ultima è valorizzata (header `X-Service-Token`). Per ruotare: imposta la nuova chiave in `SERVICE_API_KEY`, lascia la vecchia in `SERVICE_API_KEY_PREVIOUS`, aggiorna `TELEGRAM_SERVICE_API_KEY` sul bot, poi rimuovi `SERVICE_API_KEY_PREVIOUS`.

Se lo schema esiste già senza Alembic: `alembic stamp head`.

### Frontend

```bash
cd frontend
npm install
cp .env .env
npm run dev
```

```env
VITE_API_BASE_URL=http://localhost:8000
```

### Global update cron (in-app)

In `config.env` / `.env`:

```env
GLOBAL_UPDATE_CRON_ENABLED=false
GLOBAL_UPDATE_CRON_TIME=02:00
GLOBAL_UPDATE_CRON_TIMEZONE=Europe/Rome
GLOBAL_UPDATE_ALLOW_CONCURRENT_RUNS=false
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
| `app/middleware/rate_limit.py` | `RateLimitMiddleware` — tier public/admin/internal, esclusione health, 429 + `Retry-After` |
| `app/telegram/rate_limit.py` | Decorator `rate_limited` per comandi bot (messaggio IT) |

Abuso loggato con path / scope / IP o `telegram_user_id` senza token o password.

### Montate in `api/router.py` (attive)

| Metodo | Path | Handler | Auth | Ruolo |
|--------|------|---------|------|-------|
| GET | `/health` | `health.health` | pubblica | Stato app |
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

### Presenti nel codice ma non montate in `api_router` (legacy / opzionali)

Route definite in `matches.py`, `players.py`, `tournaments.py`, `ml.py` — **non** incluse in `backend/src/app/api/router.py` nella configurazione attuale. Per riattivarle: `api_router.include_router(...)`.

---

## 4. Backend — riferimento classi e metodi

### 4.1 Entry point e core

#### `app/main.py`

| Simbolo | Ruolo |
|---------|-------|
| `lifespan` | All’avvio: `reconcile_orphaned_runs`, `ensure_bootstrap_admin`, `start_global_update_scheduler`; allo shutdown ferma lo scheduler |
| `app` | Istanza FastAPI, `RateLimitMiddleware`, CORS, mount health + `api_router` |

#### `app/core/config.py` — `Settings`

Campi: `app_env`, `debug`, `database_url`, `api_prefix`, flag/cron global update, `cors_origins`, `cors_origin_regex`, auth admin (`admin_jwt_secret`, `admin_jwt_expire_minutes`, `admin_username`, `admin_password`), service token (`service_api_key`, `service_api_key_previous`, `allow_unauthenticated_service_reads`), rate limit (`rate_limit_enabled`, `rate_limit_window_seconds`, `rate_limit_public` / `_admin` / `_internal` / `_expensive` / `_login` / `_telegram` / `_telegram_expensive`).  
`get_settings()` — settings cacheati; `set_settings_override()` per test/middleware.

#### `app/core/security.py`

`hash_password` / `verify_password` (bcrypt), `create_access_token` / `decode_access_token` (JWT HS256).

#### `app/api/deps.py`

Dipendenze FastAPI: `require_admin`, `require_admin_or_service`, `require_service_token`.

#### `app/services/auth.py`

`authenticate_admin`, `issue_access_token`, `ensure_bootstrap_admin` (primo admin da env se tabella vuota).

#### `app/core/logging.py`

`configure_logging()` — setup logging applicativo standard/strutturato.  
Non esistono endpoint o file temporanei di ingest per sessioni agent (`/api/debug/agent-log` rimosso).  
Per URL/header/payload esterni usare sempre `utility/sensitive_data` prima di scrivere nei log (vedi `request_api`, migrator DB, client Telegram).

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

### 4.2 Entity (ORM legacy / dominio)

Modulo `backend/src/entity/`.

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
| `AdminUser` | Account amministratore (`admin_user`; migrazione `0011`; solo hash password) |
| `RateLimitBucket` | Contatori rate limit multi-istanza (`rate_limit_bucket`; migrazione `0012`) |

Modelli ML canonici in `app/models/ml.py`: `MLPlayer`, `MLTournament`, `MLMatch`, `RankingSnapshot`, `OddsSnapshot`, `FeatureSnapshot`.

---

### 4.3 Repository

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
| `classify_match_lifecycle` | Normalizza `event_status`/winner → `scheduled`/`live`/`finished`/`postponed`/`cancelled`/`abandoned`/`walkover`/`retired`/`unknown_problem` |
| `is_void_for_betting` | Pick void se status terminale senza winner bettable (cancelled/abandoned/…); postponed resta pending |
| `match_lifecycle_label` | Label IT per UI/Telegram |

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
| `reconcile_orphaned_runs` | Marca run zombie all’avvio app |
| `start_global_update` | Crea run e thread `_execute_global_update` |
| `cancel_global_update` | Richiesta cancel cooperativa |
| `_execute_global_update` | Import fixtures → next → predict tutte le combo → slip |
| `build_run_report` | Report strutturato della run |
| `get_models_versions_results` | Esito per modello/versione su una data |
| `get_run_by_id` / `get_latest_run` / `get_active_run` | Lettura stato |

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

#### `jobs/daily_pipeline.py` — `DailyPipeline`

`run()` esegue in ordine:

1. `run_daily_fixture_import`
2. `run_daily_next_fixture_import`
3. `run_upcoming_prediction_generation`
4. opz. `run_migration` sync cloud

`run_daily_pipeline(...)` — wrapper CLI/env (`SYNC_CLOUD`).

#### `jobs/generate_upcoming_predictions.py`

`run_upcoming_prediction_generation` — seleziona modello (best metrics o nome esplicito) e chiama `predict_upcoming_fixtures`. Default CLI/job: `model_version=v2`.

Per aggiornare **tutte** le combo modello/versione con artefatto su disco usare l’**aggiornamento globale** (`POST /api/global-update` / UI), non un job separato.

---

## 5. Frontend — riferimento moduli

### Routing (`App.tsx`)

| Path | Pagina |
|------|--------|
| `/login` | `LoginPage` (pubblica) |
| `/` | Redirect → `/predictions` (protetta) |
| `/predictions` | `PredictionsPage` |
| `/prediction-stats` | `PredictionStatsPage` |
| `/betting-slips` | `BettingSlipsPage` |
| `/betting-slip-model-stats` | `BettingSlipModelStatsPage` |
| `/global-update-report` | `GlobalUpdateReportPage` |
| `/telegram-bot` | `TelegramBotPage` |

Wrapper: `AuthProvider` → route protette con `ProtectedRoute` → `GlobalUpdateProvider` + `Layout`.

### Pagine

| Componente | Ruolo |
|------------|-------|
| `LoginPage` | Login admin; salva access token in `localStorage` |
| `PredictionsPage` | Lista partite+predizioni; margine globale (default 2%); void/decision in riga |
| `PredictionStatsPage` | Summary e serie giornaliere accuracy/ROI |
| `BettingSlipsPage` | Calendario, tab modello, 9 slip a tier, colonna media quote bookmakers, margine globale (default 2%), status pick void / quota effettiva |
| `BettingSlipModelStatsPage` | Tabella comparativa stats per modello |
| `GlobalUpdateReportPage` | Report ultima run globale: errori, warning, fasi, combo |
| `TelegramBotPage` | Analytics admin bot: KPI, filtri data/action/user, breakdown per giorno, storico eventi |

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

Client `fetch` tipizzato verso le API montate: auth (`login` / `getSession` / `logout`), predictions, betting-slips, imports, global-update, single-match-value, Telegram analytics.  
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
| Job `daily_pipeline` / `generate_upcoming_predictions` | **v2** |

Modelli tipici: `logistic_regression`, `random_forest`.

### Comandi tipici (da `backend/src`)

```bash
python -m app.ml.datasets.build_dataset --version v3
python -m app.ml.datasets.build_atp_singles --version v3
python -m app.ml.datasets.build_odds_dataset --version v3
python -m app.ml.training.train_baseline --model-version v3
python -m jobs.generate_upcoming_predictions --model-version v3
```

Artefatti:

- Dataset: `backend/data/processed/`
- Modelli: `backend/data/models/` (`v2/`, `v3/`, …)
- Metriche: `backend/data/reports/baseline_*_metrics.json`

**Anti-leakage**: feature solo con dati *precedenti* al match; `standing` corrente non usata come rank pre-match; split temporale in training.

---

## 7. Import, job e sync

```bash
# dalla cartella backend/ (o root come da SCHEDULING.md)
python -c "from src.service.basic_import import basic; basic()"
python -m src.service.import_fixtures
python -m src.jobs.daily_pipeline
python -m src.jobs.daily_pipeline --no-sync
```

Dettagli cron Windows/Linux e sync cloud: [docs/SCHEDULING.md](docs/SCHEDULING.md).

---

## 8. Bot Telegram

Modulo `app/telegram/`.

| Modulo | Ruolo |
|--------|-------|
| `config.TelegramSettings` | Token, `TELEGRAM_API_BASE_URL`, `telegram_service_api_key` (S2S, allineata a `SERVICE_API_KEY`), model version/name, `telegram_model_names` (fallback multi-modello), stake, `telegram_slip_count` (default 9), `telegram_min_edge_percent` (default 2.0) |
| `client.BackendApiClient` | Chiama le stesse API FastAPI (`/betting-slips/daily`, `/betting-slips/stats/by-model`, `/predictions/stats/summary`, `/models-versions/results`, `/next-fixtures/predictions`, `/single-match-value`, …) |
| `bot.build_application` / `main` | Polling + handler comandi |
| `rate_limit.rate_limited` | Limite comandi per `telegram_user_id` (DB condiviso; messaggio IT se superato) |
| `tracking.tracked` / `track_callback_query` | Persistenza accessi/click in `telegram_bot_event` (non blocca il bot se il DB fallisce) |
| `fixture_value.enrich_fixture_value` | Void/valore su `/partite` (SMVA o fallback da probabilità modello) |
| `messages` / `dates` / `images` / `slips_compare` / `public_labels` | Formattazione risposte, date Roma, PNG, confronto multi-serie, etichette pubbliche (accuratezza) |

Service condiviso: `app/services/telegram_analytics.py` (vedi §4.4).

**Comandi attivi:** `/start`, `/help`, `/schedine`, `/partite`, `/statistiche`.

Ogni comando (e i messaggi non gestiti / futuri callback inline) viene registrato in tabella `telegram_bot_event`. Gli aggregati e lo storico sono consultabili solo dalla dashboard admin (`/telegram-bot`), non dagli utenti del bot.

`/schedine` carica le schedine di tutti i modelli della versione configurata. Se i contenuti coincidono (stessi match e stessi vincitori previsti) ne mostra una sola serie; se differiscono anche solo per una partita/pick, mostra entrambe con etichetta pubblica basata sull’accuratezza (es. `Serie A · accuratezza 58.2%`), senza nomi tecnici. Il messaggio introduttivo contiene solo data e legenda stati (Presa / Persa / In corso / Annullata). Pick void escludono la quota dalla combinata effettiva.

`/partite` allinea la pagina **Partite**: tabella Ora/Torneo/Surface/Match/Predetto/Conf./Void/Valore/Stato (stato partita normalizzato), void+valore via SMVA (fallback da probabilità modello), multi-serie se i predittori differiscono (stesse etichette pubbliche), intro solo data+legenda stati.

`/statistiche` mostra PNG di confronto (partite + schedine con profitto/ROI) usando le stesse etichette pubbliche. Comandi pronostici (`/pronostici`, `/giorno`, `/10giorni`, `/cerca`) restano nel codice ma non sono registrati.

```bash
cd backend
python -m src.app.telegram.bot
```

---

## 9. Schema dati

Tabelle legacy import: `fixture`, `player`, `tournament`, `event`, `standing`, `next_fixture`, `match_prediction`, tabelle betting slip (`betting_slip`, `betting_slip_day`, `betting_slip_pick`) e global update (`global_update_run`, `global_update_run_item`), `telegram_bot_event` (analytics accessi bot).

Tabelle ML canoniche (migrazioni Alembic): `ml_player`, `ml_tournament`, `ml_match`, `ranking_snapshot`, `odds_snapshot`, `feature_snapshot`.

Catena migrazioni recente (Alembic): `0008_global_update_runs` → `0009_pick_min_edge_fields` → `0010_telegram_bot_events`.

```bash
cd backend
alembic upgrade head
```

---

## Test

```bash
cd backend
pytest
```

Test rilevanti: `tests/test_betting_slips.py`, `test_global_update.py`, `test_predictor.py`, `test_dataset_builder.py`, `test_train_baseline.py`, `test_match_lifecycle.py`, `test_telegram_bot.py`, `test_telegram_analytics.py`, ecc.
