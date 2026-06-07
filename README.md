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
CORS_ORIGINS=["http://localhost:5173","http://localhost:5174","http://127.0.0.1:5173","http://127.0.0.1:5174"]
CORS_ORIGIN_REGEX=^https?://(localhost|127\.0\.0\.1):\d+$
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
uvicorn src.app.main:app --reload
```

Endpoint minimi:

- `GET /health`
- `GET /api/matches`
- `GET /api/matches/{match_id}`
- `GET /api/players`
- `GET /api/players/{player_id}`
- `GET /api/tournaments`

## Avvio frontend React

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
alembic upgrade head
```

Le feature devono essere calcolate solo con dati precedenti alla data della
partita. Il builder in `src/app/ml/features/feature_builder.py` usa sempre
filtri `match_date < data_partita` e `ranking_date < data_partita` per evitare
data leakage.

Genera FeatureSnapshot ed esporta il dataset CSV:

```bash
python scripts/build_ml_dataset.py --build-features
```

Solo export da FeatureSnapshot già presenti:

```bash
python scripts/build_ml_dataset.py
```

Output predefinito:

```text
data/processed/tennis_features.csv
```

Il dataset builder (`src/app/ml/datasets/dataset_builder.py`) crea un DataFrame
pandas, esporta CSV e separa feature/target, ma non esegue training.

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