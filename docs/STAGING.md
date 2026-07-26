# Staging — ambiente separato

Stack **isolato** da locale e produzione: progetto Compose `tennis_oracle_staging`, database e volume dedicati, porte host diverse, token Telegram e secret propri.

| Artefatto | Ruolo |
|-----------|--------|
| `.env.staging.example` | Modello variabili (copiare in `.env.staging`) |
| `docker-compose.staging.yml` | Overlay: DB sempre acceso, porte, `AUTO_MIGRATE`, CORS, bot |
| `backend/scripts/run_alembic_upgrade.py` | Migrazioni controllate (`AUTO_MIGRATE`) |
| `backend/scripts/smoke_check.py` | Smoke su `/health`, `/ready`, frontend |
| `frontend/nginx.https.conf.example` | Nginx TLS opzionale (HTTPS-ready) |
| `docs/DOCKER.md` | Stack locale / prod / hot-reload |

**Non** committare `.env.staging`, certificati o token reali. **Non** riusare secret di produzione.

---

## Prerequisiti

- Docker Engine + Compose v2 (≥ 2.24 consigliato per `!reset` / `!override`)
- File `.env.staging` (da `.env.staging.example`) con password/JWT/chiavi **placeholder sostituiti**
- Token BotFather **dedicato allo staging** (mai il bot di produzione)
- Opzionale: modelli ML sul host via `MODELS_HOST_PATH`

---

## Setup

```bash
cp .env.staging.example .env.staging
# Modifica: POSTGRES_PASSWORD, ADMIN_*, SERVICE_API_KEY, TELEGRAM_*, CORS_ORIGINS, VITE_API_BASE_URL
# Allinea TELEGRAM_SERVICE_API_KEY = SERVICE_API_KEY
```

Default host (evitano conflitto con locale 8000 / 5173 / 5432):

| Servizio | Porta host |
|----------|------------|
| API | **8001** |
| Frontend | **5174** |
| Postgres staging | **5433** |

---

## Avvio

```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml \
  --env-file .env.staging up --build -d
```

- UI: `http://localhost:5174`
- API: `http://localhost:8001`
- Health: `GET /health` (liveness)
- Ready: `GET /ready` (DB raggiungibile)
- Deps: `GET /deps` (stato dipendenze / canali monitoring, senza secret)
- Metriche (se abilitate): `GET /metrics` — vedi [MONITORING.md](MONITORING.md)

### Bot Telegram di staging

```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml \
  --env-file .env.staging --profile bot up -d bot
```

### Job one-shot

```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml \
  --env-file .env.staging --profile jobs run --rm job
```

### Smoke test

```bash
python backend/scripts/smoke_check.py \
  --base-url http://localhost:8001 \
  --frontend-url http://localhost:5174 \
  --expect-env staging
```

---

## Database separato

- Servizio Compose `db` **sempre attivo** in staging (profilo `embedded-db` rimosso dall’overlay)
- Volume: `tennis_oracle_staging_postgres_data` (non condivide i dati con `tennis_oracle_postgres_data` locale)
- DB name default: `tennis_db_staging`
- `DATABASE_URL` / `DATABASE_SOURCE_URL` puntano a `db:5432` (rete Docker)

Postgres gestito esterno: imposta gli URL in `.env.staging` e non avviare `db` (oppure ferma il servizio dopo aver aggiornato gli URL). Dettaglio operativo: non usare `down -v` sul volume staging se vuoi conservare i dati.

---

## Migrazioni automatiche controllate

Il servizio `migrate` esegue `backend/scripts/run_alembic_upgrade.py`:

| `AUTO_MIGRATE` | Comportamento |
|----------------|---------------|
| `true` (default) | `alembic upgrade head` prima dell’API |
| `false` | skip (freeze schema / rollback app senza cambiare DB) |

```bash
# Solo migrate
docker compose -f docker-compose.yml -f docker-compose.staging.yml \
  --env-file .env.staging run --rm migrate
```

---

## CORS e HTTPS-ready

- `CORS_ORIGINS`: lista JSON degli origin SPA (HTTP locale e/o `https://staging.example.com`)
- `CORS_ORIGIN_REGEX`: lasciare vuoto in staging se usi solo la lista esplicita (l’API tratta stringa vuota come “nessun regex”)
- Frontend di default su **HTTP** porta pubblicata; TLS consigliato sul reverse proxy (Caddy / Traefik / LB)
- TLS nel container nginx (opzionale): monta `frontend/nginx.https.conf.example` + cert/key indicati da `STAGING_SSL_CERT` / `STAGING_SSL_KEY` (vedi commenti nel file example)

Dietro HTTPS: imposta `VITE_API_BASE_URL=https://staging-api.example.com` **prima** del build frontend e allinea `CORS_ORIGINS`.

---

## Checklist deploy staging

1. [ ] Branch/tag da pubblicare noto; immagini con `IMAGE_TAG=staging` (o tag univoco)
2. [ ] `.env.staging` aggiornato (secret forti, non di produzione)
3. [ ] Backup o snapshot volume staging (se dati da preservare); preferibile `python -m backend.src.jobs.run_db_backup` (vedi [BACKUP_DR.md](BACKUP_DR.md))
4. [ ] `AUTO_MIGRATE=true` se serve schema nuovo; altrimenti `false`
5. [ ] `docker compose … up --build -d` (file staging + `--env-file .env.staging`)
6. [ ] Smoke: `smoke_check.py --expect-env staging`
7. [ ] Login admin + smoke funzionale minimo (pronostici / health UI)
8. [ ] Bot staging (se usato): `--profile bot`, verifica token dedicato
9. [ ] `LIVE_PUBLICATION_ENABLED=false` finché non validato

---

## Checklist rollback

1. [ ] Imposta `AUTO_MIGRATE=false` se non vuoi toccare lo schema
2. [ ] Rideploy immagine/tag precedente (`IMAGE_TAG=…` o rebuild da commit noto)
3. [ ] `docker compose … up -d` (stesso overlay staging)
4. [ ] Smoke di nuovo su `/health` e `/ready`
5. [ ] Se una migrazione forward è incompatibile: ripristinare da backup volume/DB **prima** di riavviare l’API (non esiste downgrade Alembic automatico in questo stack). Restore guidato: [BACKUP_DR.md](BACKUP_DR.md) (`--mode test` poi `--mode overwrite --overwrite-source --yes`)
6. [ ] Non usare `docker compose down -v` salvo wipe intenzionale del DB staging

Arresto senza cancellare il volume:

```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml \
  --env-file .env.staging --profile bot down
# volume tennis_oracle_staging_postgres_data conservato
```

---

## Variabili principali (`.env.staging`)

| Variabile | Note |
|-----------|------|
| `APP_ENV` | `staging` |
| `POSTGRES_*` / `DATABASE_*` | DB staging separato |
| `STAGING_*_PORT` | Porte host API / FE / Postgres |
| `AUTO_MIGRATE` | Controlla Alembic al boot |
| `CORS_ORIGINS` / `CORS_ORIGIN_REGEX` | Origin SPA (HTTPS-ready) |
| `VITE_API_BASE_URL` | URL API visto dal browser (bake al build) |
| `ADMIN_*` / `SERVICE_API_KEY` | Secret solo staging |
| `TELEGRAM_BOT_TOKEN` | BotFather staging |
| `TELEGRAM_SERVICE_API_KEY` | = `SERVICE_API_KEY` |
| `LIVE_PUBLICATION_ENABLED` | Tenere `false` finché validato |

Elenco completo commentato: [`.env.staging.example`](../.env.staging.example).

---

## Troubleshooting

| Sintomo | Controllo |
|---------|-----------|
| Porta già in uso | Cambia `STAGING_*_PORT` in `.env.staging` |
| `migrate` fallisce | Log migrate; password DB; `AUTO_MIGRATE` |
| `/ready` 503 | Postgres staging healthy; `DATABASE_URL` |
| CORS bloccato | Origin esatto in `CORS_ORIGINS`; rebuild non serve per CORS (solo API) |
| FE chiama API sbagliata | `VITE_API_BASE_URL` + **rebuild** frontend |
| Bot usa produzione | Token e `TELEGRAM_*` solo da `.env.staging` |
