# Docker — avvio e arresto

Stack containerizzato per **sviluppo locale** e **produzione**. Le immagini non includono dataset, modelli `.pkl`, log né file di segreti.

| File | Ruolo |
|------|--------|
| `backend/Dockerfile` | Multi-stage API / Alembic / bot / job (Python 3.12) |
| `frontend/Dockerfile` | Multi-stage Vite build → nginx |
| `frontend/nginx.conf` | SPA static + fallback `index.html` |
| `.dockerignore` / `frontend/.dockerignore` | Esclusioni build |
| `docker-compose.yml` | Stack locale (migrate + API + frontend; DB host di default) |
| `docker-compose.dev.yml` | Overlay hot-reload (bind-mount codice, Vite + uvicorn `--reload`) |
| `docker-compose.prod.yml` | Overlay produzione |
| `docker-compose.staging.yml` | Overlay staging (DB/porte/volume separati) — vedi [STAGING.md](STAGING.md) |
| `.env.example` | Modello variabili (copiare in `.env`) |
| `.env.staging.example` | Modello staging (copiare in `.env.staging`) |

**Database di default:** PostgreSQL **sul PC** (`host.docker.internal:5432`), lo stesso di `backend/.env` (`tennis_db`).  
**db-1** (servizio Compose `db`) resta definito ma **spento** (profilo `embedded-db`); il volume `postgres_data` non viene cancellato.  
Segreti runtime: `backend/.env` (modello `backend/.env.example`). `backend/properties/config.env` resta fallback non sensibile; entrambi vengono bind-mountati. Artefatti ML sul host: `MODELS_HOST_PATH` (`.pkl` produzione, **read-only** in container), `PROCESSED_HOST_PATH` (dataset CSV per walk-forward/training, read-only), `REPORTS_HOST_PATH` (metriche JSON **e pickle calibratori ML-02** sotto `calibration/artifacts/`, scrivibile).

---

## Prerequisiti

- [Docker Engine](https://docs.docker.com/engine/install/) + Compose v2 (consigliato ≥ 2.24 per l’overlay prod)
- PostgreSQL **locale** in esecuzione su `5432` con database `tennis_db`
- File `.env` in root (parti da `.env.example`)
- Opzionale: artefatti in `backend/data/models/` sul host
- Per walk-forward / training in container: CSV in `backend/data/processed/` sul host (montati via `PROCESSED_HOST_PATH`)

---

## Setup iniziale

```bash
cp .env.example .env
# DATABASE_URL punta a host.docker.internal (non localhost, non db)
# Segreti app: backend/.env (parti da backend/.env.example)
# config.env contiene solo fallback non sensibile
# Non committare secret
```

Default locali: UI **5173**, API **8000**, stesso DB del lavoro senza Docker.

---

## Avvio (locale)

Assicurati che Postgres sul PC sia acceso, poi:

```bash
# migrate + api + frontend (db-1 NON parte)
docker compose up --build -d

curl http://localhost:8000/health
curl http://localhost:8000/deps
# UI: http://localhost:5173
# API: http://localhost:8000
# Monitoring (log/metriche/alert): docs/MONITORING.md
```

`migrate` esegue `alembic upgrade head` sul DB host e termina; l’API parte solo se la migrazione ha successo.

### Migrazioni

```bash
docker compose run --rm migrate
```

### Bot Telegram

```bash
docker compose --profile bot up -d bot
```

### Job giornaliero

One-shot sullo stesso orchestratore del pulsante UI (`run_global_update`):

```bash
docker compose --profile jobs run --rm job
```

Vedi [SCHEDULING.md](SCHEDULING.md) (lock, resume, exit code, sync cloud).

---

## Modalità sviluppo (hot-reload)

Per vedere subito le modifiche a backend/frontend **senza** `docker compose build` a ogni salvataggio, usa l’overlay `docker-compose.dev.yml`.

Lo stack “prod-like” (`docker compose up --build`) resta disponibile per prove con immagini baked + nginx.

### Differenza

| | Prod-like (`docker-compose.yml`) | Dev (`… + docker-compose.dev.yml`) |
|--|----------------------------------|-------------------------------------|
| Codice | Copiato nell’immagine al build | Bind-mount da disco (`backend/src`, `frontend/`) |
| API | `uvicorn` senza reload | `uvicorn --reload` |
| Frontend | nginx + bundle statico | Vite `npm run dev` (HMR) |
| Dopo edit codice | `build` + `up -d` | salva e attendi reload/HMR |
| Bot | codice baked | stesso mount di `backend/src` (restart senza rebuild) |
| DB | `host.docker.internal` (invariato) | uguale |

### Avvio

Ferma prima lo stack prod-like se è già su 5173/8000 (stesse porte):

```bash
docker compose --profile bot down
# oppure solo stop, senza -v

# Prima volta: serve l’immagine backend (migrate/api). Poi non serve rebuild a ogni edit.
docker compose -f docker-compose.yml -f docker-compose.dev.yml build api
docker compose -f docker-compose.yml -f docker-compose.dev.yml up

# Con bot:
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile bot up
```

In background: aggiungi `-d`.

- UI: `http://localhost:5173` (Vite)
- API: `http://localhost:8000`
- Il frontend al primo avvio esegue `npm ci` (può richiedere 1–2 minuti)

### Arresto

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile bot down
# volume node_modules del container FE conservato; non usare -v se non serve
```

### Bot in dev

Il codice del bot è montato, quindi **non** serve `build` dopo un edit. Il processo Telegram non ha HMR nativo: dopo modifiche sotto `backend/src/app/telegram` (o dipendenze condivise):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile bot restart bot
```

### Quando usare cosa

| Scenario | Comando |
|----------|---------|
| Coding quotidiano in Docker con reload | `… -f docker-compose.dev.yml up` |
| Verifica “come in produzione” (nginx, bundle) | `docker compose up --build -d` |
| Solo PC, senza Docker app | `uvicorn --reload` + `npm run dev` |

### Limiti

- Su **Windows/macOS** il file watching usa polling (`WATCHFILES_FORCE_POLLING` / `CHOKIDAR_USEPOLLING`) — un po’ più di CPU, ma affidabile con Docker Desktop.
- Job (`profile jobs`) resta one-shot come nello stack base (nessun hot-reload dedicato).
- Cambi a `requirements.txt` / `package.json` richiedono ancora rebuild o, per il FE, cancellare il volume `tennis_oracle_frontend_dev_node_modules` e riavviare.
- Non mescolare contemporaneamente prod-like e dev sulle stesse porte.

---

## Dopo modifiche al codice (stack prod-like, senza hot-reload)

Le immagini Docker **non** montano il codice sorgente: dopo un cambiamento serve **rebuild** del servizio toccato (non basta riavviare il container).

### Backend (Python)

```bash
docker compose build api
docker compose up -d api
# se il bot è attivo (stessa immagine backend):
docker compose --profile bot up -d --force-recreate bot
```

### Frontend (React / TypeScript / CSS)

```bash
docker compose build frontend
docker compose up -d frontend
```

Obbligatorio anche se cambi solo `VITE_API_BASE_URL` in `.env` (variabile bake-ata al build Vite).

### Backend e frontend insieme

```bash
docker compose build api frontend
docker compose up -d api frontend
docker compose --profile bot up -d --force-recreate bot   # se usi il bot
```

### Cosa non richiede rebuild dell’immagine

| Cosa cambi | Azione |
|------------|--------|
| `backend/.env` / `backend/properties/config.env` | `docker compose up -d --force-recreate api` (+ bot se attivo); `backend/.env` ha precedenza |
| Solo modelli `.pkl` sotto `MODELS_HOST_PATH` | nessuna (già montati in sola lettura) |
| Dataset CSV sotto `PROCESSED_HOST_PATH` / report sotto `REPORTS_HOST_PATH` | nessuna (già montati; recreate `api` se hai appena aggiunto i volume) |
| Solo documentazione | nessuna |
| Nuova migrazione Alembic | `docker compose run --rm migrate` (poi riavvia `api` se serve) |

### Sviluppo quotidiano (alternativa senza rebuild)

**Opzione A — Docker hot-reload:** [Modalità sviluppo](#modalità-sviluppo-hot-reload) (`docker-compose.dev.yml`).

**Opzione B — processi sul PC** (stesso Postgres locale):

```bash
# backend (da backend/, venv attivo)
uvicorn src.app.main:app --reload

# frontend (da frontend/)
npm run dev
```

Usa lo stack prod-like (`docker compose up --build`) quando vuoi verificare immagini baked + nginx.

---

## Postgres embedded (db-1), opzionale

Non avviato di default. Volume `tennis_oracle_postgres_data` resta intatto.

```bash
# Avvia solo db-1
docker compose --profile embedded-db up -d db

# Punta l’app al container (in .env):
# DATABASE_URL=postgresql://postgres:postgres@db:5432/tennis_db
# DATABASE_SOURCE_URL=postgresql://postgres:postgres@db:5432/tennis_db
docker compose up -d --force-recreate migrate api
```

Per tornare al DB del PC: ripristina `host.docker.internal` in `.env`, ferma db senza cancellare il volume:

```bash
docker compose --profile embedded-db stop db
# non usare: docker compose down -v
```

---

## Arresto

```bash
docker compose --profile bot stop
docker compose stop

# Rimuove i container; volume embedded (se esiste) CONSERVATO
docker compose --profile bot down

# ATTENZIONE: cancella anche il volume postgres_data di db-1
# docker compose down -v
```

---

## Staging

Ambiente separato (DB, volume, porte, bot, secret propri). Guida completa e checklist deploy/rollback: [STAGING.md](STAGING.md).

```bash
cp .env.staging.example .env.staging   # poi modifica i placeholder
docker compose -f docker-compose.yml -f docker-compose.staging.yml \
  --env-file .env.staging up --build -d
# UI http://localhost:5174  —  API http://localhost:8001/health + /ready
python backend/scripts/smoke_check.py --base-url http://localhost:8001 \
  --frontend-url http://localhost:5174 --expect-env staging
```

## Produzione

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

In prod di solito userai un Postgres gestito (URL in `.env`), non `host.docker.internal`. Il profilo `embedded-db` resta disponibile se ti serve un Postgres nel compose.

---

## Cosa non finisce nelle immagini

- `backend/data/processed`, `backend/data/models` / `*.pkl`
- `**/.env`, `backend/properties/config.env`
- `node_modules`, log, coverage, backup SQL / dump (`backups/`)

Backup e disaster recovery PostgreSQL (host o embedded): [BACKUP_DR.md](BACKUP_DR.md).

---

## Troubleshooting

| Sintomo | Cosa controllare |
|---------|------------------|
| `migrate` / API non connettono al DB | Postgres sul PC acceso; `DATABASE_URL` con `host.docker.internal`; password allineata a `backend/.env` |
| Porta 5432 in conflitto | Non avviare il profilo `embedded-db` insieme al Postgres host sulla stessa porta |
| Frontend API sbagliata | `VITE_API_BASE_URL` al build (URL del browser) |
| Nessuna previsione ML | `MODELS_HOST_PATH` e `.pkl` sul host |
| Walk-forward fallisce subito (0 fold, `FileNotFoundError` dataset) | CSV in `backend/data/processed/` sul host; volume `PROCESSED_HOST_PATH` montato su `api`/`job`; poi `docker compose up -d --force-recreate api` |
| Bot non parte | profilo `bot`, `TELEGRAM_BOT_TOKEN`, API healthy |
| Frontend Vite non aggiorna / non parte | Log `frontend`; primo `npm ci`; polling; porta 5173 libera |
| Bot non vede edit Python | `restart bot` (dev); oppure rebuild nello stack prod-like |
| Hot-reload non parte | Usa entrambi i file: `-f docker-compose.yml -f docker-compose.dev.yml` |
