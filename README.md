# tennis_oracle

Backend FastAPI e pipeline Python per importare dati tennis da API esterna in
PostgreSQL (`tennis_db`), esporli via API e sincronizzarli verso un database
target.

## Setup locale

1. Crea un virtualenv e installa le dipendenze:

```bash
pip install -r requirements.txt
```

2. Crea il file `.env` dalla configurazione di esempio:

```bash
cp .env.example .env
```

3. Imposta almeno queste variabili:

```env
APP_ENV=local
DEBUG=false
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tennis_db
```

Per gli import dall'API tennis continua a essere supportato anche
`properties/config.env`, che deve contenere `API_TENNIS_KEY` e
`API_TENNIS_BASE`.

## Migrazioni Alembic

Applica lo schema PostgreSQL:

```bash
alembic upgrade head
```

Se `tennis_db` esiste già con le stesse tabelle create in passato via
SQLAlchemy, verifica lo schema prima di eseguire la migration iniziale. In quel
caso puoi registrare lo stato corrente con:

```bash
alembic stamp head
```

## Avvio backend FastAPI

```bash
uvicorn backend.app.main:app --reload
```

Endpoint minimi:

- `GET /health`
- `GET /api/matches`
- `GET /api/matches/{match_id}`
- `GET /api/players`
- `GET /api/players/{player_id}`
- `GET /api/tournaments`

## Comandi import esistenti

```bash
# Bootstrap eventi e tornei
python -c "from src.service.basic_import import basic; basic()"

# Import fixtures
python -m src.service.import_fixtures

# Pipeline giornaliera import + sync
python -m src.jobs.daily_pipeline

# Solo import locale, senza sync cloud
python -m src.jobs.daily_pipeline --no-sync
```