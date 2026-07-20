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
cp .env.example .env
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
```

Per gli import API tennis: `backend/properties/config.env` con `API_TENNIS_KEY` e `API_TENNIS_BASE` (vedi `config.env.example`).

Se lo schema esiste già senza Alembic: `alembic stamp head`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
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

### Montate in `api/router.py` (attive)

| Metodo | Path | Handler | Ruolo |
|--------|------|---------|-------|
| GET | `/health` | `health.health` | Stato app |
| GET | `/api/imports/status` | `imports.read_import_status` | Ultimo stato import |
| POST | `/api/imports/refresh` | `imports.refresh_upcoming_matches` | Refresh next fixtures + predizioni |
| POST | `/api/imports/fixtures` | `imports.import_completed_fixtures` | Import partite giocate |
| GET | `/api/next-fixtures` | `predictions.read_next_fixtures` | Prossime partite |
| GET | `/api/next-fixtures/predictions` | `predictions.read_next_fixtures_predictions` | Partite + predizione paginate |
| GET | `/api/predictions/stats/daily` | `predictions.read_daily_prediction_stats` | Stats giornaliere |
| GET | `/api/predictions/stats/summary` | `predictions.read_prediction_summary` | Riepilogo accuracy/ROI |
| GET | `/api/single-match-value` | `single_match_value.read_single_match_value_analysis` | Analisi value bet (margine globale default 2%) |
| GET | `/api/betting-slips/daily` | `betting_slips.read_daily_betting_slips` | Schedine del giorno (9 profili a tier) |
| POST | `/api/betting-slips/daily` | `betting_slips.generate_daily_betting_slips` | Rigenera schedine del giorno |
| GET | `/api/betting-slips/calendar` | `betting_slips.read_betting_slip_calendar` | Calendario giorni con schedine |
| POST | `/api/betting-slips/refresh` | `betting_slips.refresh_daily_betting_slips` | Refresh import + rigenera schedine |
| GET | `/api/betting-slips/stats` | `betting_slips.read_betting_slip_stats` | Stats schedine |
| GET | `/api/betting-slips/stats/by-model` | `betting_slips.read_betting_slip_stats_by_model` | Stats per modello |
| POST | `/api/global-update` | `global_update.trigger_global_update` | Avvia aggiornamento globale |
| GET | `/api/global-update/status` | `global_update.read_global_update_status` | Run attiva |
| GET | `/api/global-update/latest` | `global_update.read_latest_global_update` | Ultima run |
| GET | `/api/global-update/{run_id}` | `global_update.read_global_update_run` | Dettaglio run |
| GET | `/api/global-update/{run_id}/report` | `global_update.read_global_update_report` | Report run |
| POST | `/api/global-update/{run_id}/cancel` | `global_update.cancel_global_update_run` | Annulla run |
| GET | `/api/models-versions/results` | `global_update.read_models_versions_results` | Risultati per versione/modello |

### Presenti nel codice ma non montate in `api_router` (legacy / opzionali)

Route definite in `matches.py`, `players.py`, `tournaments.py`, `ml.py` — **non** incluse in `backend/src/app/api/router.py` nella configurazione attuale. Per riattivarle: `api_router.include_router(...)`.

---

## 4. Backend — riferimento classi e metodi

### 4.1 Entry point e core

#### `app/main.py`

| Simbolo | Ruolo |
|---------|-------|
| `lifespan` | All’avvio: `reconcile_orphaned_runs` + `start_global_update_scheduler`; allo shutdown ferma lo scheduler |
| `app` | Istanza FastAPI, CORS, mount health + `api_router` |

#### `app/core/config.py` — `Settings`

Campi: `app_env`, `debug`, `database_url`, `api_prefix`, flag/cron global update, `cors_origins`, `cors_origin_regex`.  
`get_settings()` — settings cacheati (`lru_cache`).

#### `app/core/logging.py`

`configure_logging()` — setup logging applicativo.

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
| `BettingSlip` / `BettingSlipDay` / `BettingSlipPick` | Schedine e selezioni |
| `GlobalUpdateRun` / `GlobalUpdateRunItem` | Stato aggiornamento globale e step per combo modello |

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

`run_upcoming_prediction_generation` — seleziona modello (best metrics o nome esplicito) e chiama `predict_upcoming_fixtures`.

#### `jobs/all_models_daily_update.py`

Variante multi-modello dell’aggiornamento giornaliero.

---

## 5. Frontend — riferimento moduli

### Routing (`App.tsx`)

| Path | Pagina |
|------|--------|
| `/` | Redirect → `/predictions` |
| `/predictions` | `PredictionsPage` |
| `/prediction-stats` | `PredictionStatsPage` |
| `/betting-slips` | `BettingSlipsPage` |
| `/betting-slip-model-stats` | `BettingSlipModelStatsPage` |
| `/global-update-report` | `GlobalUpdateReportPage` |

Wrapper: `GlobalUpdateProvider`.

### Pagine

| Componente | Ruolo |
|------------|-------|
| `PredictionsPage` | Lista partite+predizioni; margine globale (default 2%); void/decision in riga |
| `PredictionStatsPage` | Summary e serie giornaliere accuracy/ROI |
| `BettingSlipsPage` | Calendario, tab modello, 9 slip a tier, margine globale (default 2%), status pick void / quota effettiva |
| `BettingSlipModelStatsPage` | Tabella comparativa stats per modello |
| `GlobalUpdateReportPage` | Report ultima run globale: errori, warning, fasi, combo |

### Componenti / hook

| Modulo | Ruolo |
|--------|-------|
| `Layout` | Sidebar, nav, slot `GlobalUpdateControls` |
| `GlobalUpdateControls` | Start/cancel/status aggiornamento globale; link a report se ci sono errori |
| `ModelControls` | Selettore versione/nome modello |
| `Status` | `LoadingState` / `ErrorState` / `EmptyState` |
| `MetricCard` | Card metrica |
| `useGlobalUpdate` | Context: polling status, start/cancel |

### `services/apiClient.ts`

Client `fetch` tipizzato verso le API montate (predictions, betting-slips, imports, global-update, single-match-value).  
`ApiError` — errore HTTP con `status`.

### Utils

- `utils/modelVersion.ts` — default `v3`, persistenza localStorage; `resolvePreferredModelVersion` su Predictions / Betting slips / Stats
- `utils/minEdge.ts` — classificazione PLAY/BORDERLINE/NO BET lato client
- `utils/tennis.ts` — format date/score/superficie/nomi giocatore
- `types/api.ts` — tipi TypeScript allineati agli schema Pydantic

---

## 6. Pipeline ML

### Versioni

| Versione | Idea | Odds in training/inferenza |
|----------|------|----------------------------|
| **v1** | Baseline forma/H2H/ATP parziale | No (solo post-hoc edge) |
| **v2** | Rank storico, Elo, forma, H2H, ATP | No (solo post-hoc) |
| **v3** | Feature v2 + aggregati quote pre-match | Sì (solo match con odds) |

Default UI/API: **v2**. Modelli tipici: `logistic_regression`, `random_forest`.

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
| `config.TelegramSettings` | Token, `TELEGRAM_API_BASE_URL`, model version/name, `telegram_model_names` (fallback multi-modello), stake, `telegram_slip_count` (default 9), `telegram_min_edge_percent` (default 2.0) |
| `client.BackendApiClient` | Chiama le stesse API FastAPI (`/betting-slips/daily`, `/betting-slips/stats/by-model`, `/predictions/stats/summary`, `/models-versions/results`, `/next-fixtures/predictions`, …) |
| `bot.build_application` / `main` | Polling + handler comandi |
| `messages` / `dates` / `images` / `slips_compare` / `public_labels` | Formattazione risposte, date Roma, PNG, confronto multi-serie, etichette pubbliche (accuratezza) |

**Comandi attivi:** `/start`, `/help`, `/schedine`, `/partite`, `/statistiche`.

`/schedine` carica le schedine di tutti i modelli della versione configurata. Se i contenuti coincidono (stessi match e stessi vincitori previsti) ne mostra una sola serie; se differiscono anche solo per una partita/pick, mostra entrambe con etichetta pubblica basata sull’accuratezza (es. `Serie A · accuratezza 58.2%`), senza nomi tecnici. Il messaggio introduttivo contiene solo data e legenda stati (Presa / Persa / In corso / Annullata). Pick void escludono la quota dalla combinata effettiva.

`/partite` allinea la pagina **Partite**: tabella Ora/Torneo/Surface/Match/Predetto/Conf./Void/Valore/Stato (stato partita normalizzato), void+valore via SMVA (fallback da probabilità modello), multi-serie se i predittori differiscono (stesse etichette pubbliche), intro solo data+legenda stati.

`/statistiche` mostra PNG di confronto (partite + schedine con profitto/ROI) usando le stesse etichette pubbliche. Comandi pronostici (`/pronostici`, `/giorno`, `/10giorni`, `/cerca`) restano nel codice ma non sono registrati.

```bash
cd backend
python -m src.app.telegram.bot
```

---

## 9. Schema dati

Tabelle legacy import: `fixture`, `player`, `tournament`, `event`, `standing`, `next_fixture`, `match_prediction`, tabelle betting slip e global update.

Tabelle ML canoniche (migrazioni Alembic): `ml_player`, `ml_tournament`, `ml_match`, `ranking_snapshot`, `odds_snapshot`, `feature_snapshot`.

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

Test rilevanti: `tests/test_betting_slips.py`, `test_global_update.py`, `test_predictor.py`, `test_dataset_builder.py`, `test_train_baseline.py`, `test_telegram_bot.py`, ecc.

Frontend: test Vitest dove presenti (es. `ModelsControlPage.test.tsx`).
