# Layer backend: services / service / repository / entity

Documento di analisi della duplicazione architetturale. **Non è un refactoring totale**: descrive lo stato attuale, la struttura canonica e un piano di migrazione incrementale.

Stato al 2026-07-22. Dopo ogni step di migrazione, aggiornare la sezione [Stato migrazione](#stato-migrazione).

---

## 1. Mappa delle dipendenze

```text
HTTP / bot / scheduler / jobs
        │
        ▼
┌───────────────────────┐
│  app/api/routes/*     │  (montate in api/router.py)
│  app/telegram/*       │
│  app/scheduler.py     │
│  jobs/*               │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐     facade     ┌──────────────────────────┐
│  app/services/*       │ ─────────────► │  service/* (import API)  │
│  (logica applicativa) │                │  + repository/* (CRUD)   │
└───────────┬───────────┘                └────────────┬─────────────┘
            │                                         │
            │  Session via app.db.session             │  SessionLocal
            │  (query SQLAlchemy moderne)             │  (CrudRepository)
            ▼                                         ▼
┌───────────────────────┐                ┌──────────────────────────┐
│  entity/*  (ORM)      │ ◄──────────────│  stesse classi entity    │
│  app/models (re-export│                └──────────────────────────┘
│   + modelli ML)       │
└───────────────────────┘
```

**Direzione tipica oggi**

| Da | Verso | Note |
|----|-------|------|
| `api/routes/*` montate | `app/services/*` | Path canonico HTTP |
| `app/services/imports.py`, `global_update.py` | `service/import_*` | Facade verso import legacy |
| `service/import_*` | `repository/*` → `entity/*` | Scritture/letture import |
| `app/services/*` (predictions, slips, …) | `app/models` / `entity` + `Session` | Bypass repository |
| `jobs/run_global_update.py` / `daily_pipeline.py` | `global_update` (+ opz. migrator) | Job batch = stesso orchestratore UI |
| `jobs/generate_upcoming_predictions.py` | `app/services/predictions` + ML | Mix nuovo |
| ML (`app/ml/*`) | `entity` / `app/models` / a volte `repository_db.SessionLocal` | Storico vs path moderni |

---

## 2. Componenti attivi

### `app/services/` (canonico per dominio applicativo)

| Modulo | Usato da | Ruolo |
|--------|----------|-------|
| `auth.py` | routes auth, deps, main | Admin JWT / bootstrap |
| `predictions.py` | routes predictions, slips, SMVA, jobs, import_state | Liste fixture + stats pronostici |
| `published_predictions.py` | routes published_predictions | Registro immutabile pubblicazioni (append-only) |
| `live_publication_service.py` | global_update | Pubblica PLAY della combo pubblica nel tipbook live |
| `live_betting_metrics.py` | published_live_stats | Formule pure tipbook live (hit rate, ROI/yield, drawdown, streak) |
| `published_live_stats.py` | routes published_predictions `/stats`, live_beta_dashboard | KPI live dal ledger (separate da training/backtest e stats operative) |
| `live_beta_dashboard.py` | routes live_beta_dashboard | Aggregato admin beta live (pipeline, tipbook, bot, completezza, errori) |
| `prematch_odds_snapshots.py` | routes prematch_odds_snapshots, import_next_fixtures | Storico append-only quote pre-match |
| `betting_slips.py` | routes betting_slips, global_update | Schedine |
| `single_match_value.py` | routes SMVA, betting_slips | Value bet |
| `match_lifecycle.py` | predictions, betting_slips, published_predictions, published_live_stats, telegram | Classificazione stati + settlement idempotente (singole/schedine/void) |
| `global_update.py` | routes, scheduler, main | Aggiornamento globale |
| `imports.py` / `import_state.py` | routes imports, global_update, slips | Orchestrazione refresh + stato |
| `telegram_analytics.py` | routes telegram, bot tracking | Analytics bot |

### `service/` (attivo, ma layer import legacy)

| Modulo | Usato da | Ruolo |
|--------|----------|-------|
| `import_fixtures.py` | `app/services/imports`, global_update, daily_pipeline | Import fixture giocate |
| `import_next_fixtures.py` | idem + test dedicati | Next fixture + promozione |
| `import_stading_player.py` | `import_fixtures` | Standing + player |
| `database_migrator.py` | step sync di `global_update` / job CLI | Copia SOURCE→TARGET |

### `entity/` (ORM di dominio — attivo)

Tutte le tabelle operative: `Fixture`, `NextFixture`, `MatchPrediction`, slips, `GlobalUpdateRun*`, `AdminUser`, `TelegramBotEvent`, `RateLimitBucket`, `PublishedPrediction`, `PrematchOddsSnapshot`, ecc. Fonte di verità ORM.

### `repository/` (attivo solo per import)

Usato da `service/import_*`. Non usato da `app/services` di lettura/API (che query-ano con `Session` FastAPI).

### `app/models`

- Re-export di gran parte di `entity/*` per i service moderni
- Più modelli ML in `app/models/ml.py` (`MLMatch`, …)

---

## 3. Componenti legacy / opzionali

| Componente | Motivo |
|------------|--------|
| `api/routes/matches.py`, `players.py`, `tournaments.py`, `ml.py` | Definite ma **non montate** in `api/router.py` |
| `app/services/matches.py`, `players.py`, `tournaments.py` | Solo per route non montate |
| `service/basic_import.py` | Bootstrap eventi/tornei; invocabile a mano / script, non dal flusso HTTP quotidiano |
| `repository/base/operationDB.py` | Helper Alembic/reset; **nessun import** dal codice applicativo attivo |
| Pattern `CrudRepository` + sessioni a vita lunga | Stile pre-FastAPI; parallelo a `get_db()` |

---

## 4. Duplicazioni

1. **Due “service layer”**
   - `app/services/*` = dominio + API
   - `service/*` = import HTTP verso API tennis + persistenza via repository
2. **Due accessi DB**
   - Moderno: `app.db.session.SessionLocal` / `get_db()` + query nei service
   - Legacy: `repository` + `CrudRepository` (session factory propria, ora allineata — vedi step 1)
3. **Due path ORM**
   - `from backend.src.entity import Fixture`
   - `from backend.src.app.models import Fixture` (stessa classe, re-export)
4. **Due registry modelli**
   - `entity/__init__.py` e `app/db/base.py` / `app/models/__init__.py` importano le stesse entity per metadata Alembic/test
5. **CRUD vs query ad hoc**
   - Repository generico (`save`, `search_filter`, …) vs `select(...)` nei service moderni — stessa tabella, stilisticamente diverso

---

## 5. Codice non utilizzato (o quasi)

| Elemento | Evidenza |
|----------|----------|
| `OperationDB` / `operationDB` | Nessun import fuori dal proprio file |
| Route `matches` / `players` / `tournaments` / `ml` | Non in `api_router` |
| Service `matches` / `players` / `tournaments` | Solo da quelle route |
| `DATABASE_PATH` / sqlite in vecchio `repository_db` | Residuo storico (rimosso nello step 1) |
| `basic_import` nel path caldo | Solo script/manuale (README) |

Non eliminare questi moduli senza decisione esplicita: possono servire a bootstrap, debug o riattivazione API.

---

## 6. Struttura canonica proposta

```text
backend/src/app/
  api/routes/          # solo HTTP
  services/            # TUTTA la logica applicativa (incluso import orchestrato)
  db/session.py        # unico engine + SessionLocal + get_db
  models/              # SOLO modelli ML (+ eventualmente thin re-export deprecato)
  schemas/             # Pydantic

backend/src/entity/    # ORM di dominio (unica home delle tabelle operative)
                       # oppure, in uno step futuro: spostare sotto app/models/domain/

backend/src/jobs/      # entry CLI/cron che chiamano app.services

# Da ritirare gradualmente:
backend/src/service/       → funzioni spostate in app/services/imports_* 
backend/src/repository/    → query/upsert nei service o piccoli repository in app/
```

**Regole canoniche**

1. Nuovo codice di dominio → solo `app/services` + `Session`/`get_db`.
2. Nuove tabelle → `entity/` (finché non si decide lo spostamento fisico).
3. Import API tennis → restano isolabili, ma l’entry point pubblico resta `app/services/imports.py`.
4. Non introdurre nuovi `CrudRepository` / nuovi moduli sotto `service/`.
5. Preferire `entity` (o un unico re-export documentato); evitare di moltiplicare alias.

---

## 7. Piano incrementale di migrazione

| Step | Intervento | Rischio | Stato |
|------|------------|---------|-------|
| **1** | Unificare `repository_db` su `app.db.session` (un solo engine/pool); documentare layer | Basso | **Fatto** |
| 2 | Far passare ML scripts (`build_dataset`, …) a `app.db.session` invece di `repository_db` | Basso | Da fare |
| 3 | Marcare / deprecare route e service non montati (`matches`/`players`/`tournaments`) senza cancellarli | Basso | Da fare |
| 4 | Spostare orchestration già in `app/services/imports` come unico API; `service/import_*` diventano `_impl` interni (stesso comportamento) | Medio | Da fare |
| 5 | Ridurre uso di `CrudRepository` negli import: upsert espliciti con Session breve | Medio | Da fare |
| 6 | Convergere import ORM su un solo path (`entity` o `app.models`) | Basso–medio | Da fare |
| 7 | Valutare rimozione `operationDB` / `basic_import` se sostituiti da Alembic + comandi documentati | Basso | Da fare |
| 8 | (Opzionale) Rinominare/spostare `service/` → `app/services/integrations/` | Alto (import path) | Solo con alias di compatibilità |

Ogni step: compatibilità import path, test backend, aggiornamento di questo file e del README §1 / §4.

---

## Stato migrazione

- **Completato**: step 1 — `repository/base/repository_db.py` re-esporta `engine` e `SessionLocal` da `app.db.session`; i test di API riallineano anche il modulo repository quando rebindano la session factory.
- **Resta da migrare**: step 2–8 (vedi tabella). Nessun spostamento di logica import o eliminazione repository in questo intervento.
