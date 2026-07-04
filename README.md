# tennis_oracle

Monorepo con backend FastAPI (`backend/`) e frontend React (`frontend/`).

Il backend importa dati tennis da API esterna in PostgreSQL (`tennis_db`), li espone via API e li sincronizza verso un database target.

## Setup backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
```

Imposta almeno queste variabili in `backend/.env`:

```env
APP_ENV=local
DEBUG=false
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tennis_db
CORS_ORIGINS=["http://localhost:5173","http://localhost:5174","http://127.0.0.1:5173","http://127.0.0.1:5174"]
CORS_ORIGIN_REGEX=^https?://(localhost|127\.0\.0\.1):\d+$
```

Per gli import dall'API tennis continua a essere supportato anche
`backend/properties/config.env`, che deve contenere `API_TENNIS_KEY` e
`API_TENNIS_BASE`.

### Migrazioni Alembic

Applica lo schema PostgreSQL (dalla cartella `backend/`):

```bash
cd backend
alembic upgrade head
```

Se `tennis_db` esiste già con le stesse tabelle create in passato via
SQLAlchemy, verifica lo schema prima di eseguire la migration iniziale. In quel
caso puoi registrare lo stato corrente con:

```bash
alembic stamp head
```

### Avvio backend FastAPI

```bash
cd backend
uvicorn src.app.main:app --reload
```

Endpoint minimi:

- `GET /health`
- `GET /api/matches`
- `GET /api/matches/{match_id}`
- `GET /api/players`
- `GET /api/players/{player_id}`
- `GET /api/tournaments`

## Setup frontend

Il frontend vive in `frontend/` ed espone una prima UI per dashboard,
partite, giocatori, dettaglio giocatore e tornei.

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Configura l'URL del backend in `frontend/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

## Base dati ML-ready

Le tabelle legacy usate dagli import (`fixture`, `player`, `tournament`) restano
intatte. Per ML/DL sono state aggiunte tabelle canoniche separate:

- `ml_player`
- `ml_tournament`
- `ml_match`
- `ranking_snapshot`
- `odds_snapshot`
- `feature_snapshot`

Applica le migrazioni:

```bash
cd backend
alembic upgrade head
```

Le feature devono essere calcolate solo con dati precedenti alla data della
partita. Con lo schema attuale il dataset builder legge direttamente dalle
tabelle legacy `fixture` e `tournament`: usa `fixture` per match, player, data e
target, e `tournament.tournament_sourface` come `surface`.

Crea il dataset CSV addestrabile:

```bash
cd backend/src
python -m app.ml.datasets.build_dataset
```

Output predefinito:

```text
backend/data/processed/tennis_winner_dataset.csv
```

Arricchimento opzionale ATP singles, usando i CSV in
`backend/data/processed/tennis_atp-master`:

```bash
cd backend/src
python -m app.ml.datasets.build_atp_singles
```

Questo comando non sovrascrive il dataset base e crea:

- `backend/data/processed/atp_singles_matches_normalized.csv`
- `backend/data/processed/atp_singles_match_mapping.csv`
- `backend/data/processed/atp_singles_player_mapping.csv`
- `backend/data/processed/tennis_winner_dataset_atp_enriched.csv`

Il dataset builder (`backend/src/app/ml/datasets/dataset_builder.py`) crea un
DataFrame pandas, calcola storico forma/H2H scorrendo i match in ordine
temporale, gestisce rank/Elo mancanti con valori numerici puliti, esporta CSV e
separa feature/target, ma non esegue training. Le classifiche in `standing` sono
correnti e non storiche, quindi non vengono usate come ranking pre-match per
evitare data leakage. Per il training usa uno split temporale, ad esempio train
sulle date più vecchie e validation/test sulle date più recenti.

## Comandi import esistenti

Esegui dalla cartella `backend/`:

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
