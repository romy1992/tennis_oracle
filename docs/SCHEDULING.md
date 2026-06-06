# Scheduling giornaliero (09:00)

## Cosa fa il job

`DailyPipeline` (`src/jobs/daily_pipeline.py`):

1. **Import fixtures** nel DB locale (ieri → oggi, come `import_fixtures`)
2. **Sync cloud** verso `DATABASE_TARGET_URL` con upsert (default tabella `fixture`)

Comando unico:

```bash
python3 -m src.jobs.daily_pipeline
```

## Configurazione (`properties/config.env`)

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tennis_db
DATABASE_SOURCE_URL=postgresql://postgres:postgres@localhost:5432/tennis_db
DATABASE_TARGET_URL=postgresql://postgres:postgres@<host-cloud>:5432/tennis_db
SYNC_CLOUD=true
```

- `DATABASE_URL` / `DATABASE_SOURCE_URL`: DB sul **tuo PC**
- `DATABASE_TARGET_URL`: DB sul **server cloud agent**
- Il cloud agent **non** raggiunge il tuo `localhost` senza tunnel SSH o host esposto

Prima di schedulare il job, installa le dipendenze e applica lo schema:

```bash
pip install -r requirements.txt
alembic upgrade head
```

## Cron sul tuo PC (consigliato per DB locale)

### Linux / macOS

```bash
mkdir -p /percorso/tennis_oracle/logs
chmod +x /percorso/tennis_oracle/scripts/run_daily_job.sh
crontab -e
```

Aggiungi (adatta il percorso):

```cron
0 9 * * * /percorso/tennis_oracle/scripts/run_daily_job.sh
```

### Windows (Task Scheduler)

1. **Utilità di pianificazione** → Crea attività di base
2. Trigger: ogni giorno alle **09:00**
3. Azione: avvia programma  
   - Programma: `C:\percorso\tennis_oracle\scripts\run_daily_job.bat`  
   - Oppure: `python` con argomenti `-m src.jobs.daily_pipeline`  
   - Cartella iniziale: root del progetto

## Cursor Automations (agent cloud): quando usarle?

| Obiettivo | Soluzione |
|-----------|-----------|
| Scrivere nel **DB locale sul PC** | **Cron / Task Scheduler sul PC** (questa guida) |
| Job solo sul **DB cloud** | Cursor **Automations** (agent in cloud) |
| Entrambi (locale + cloud) | **Cron sul PC** che esegue `daily_pipeline` (import locale + sync verso cloud) |

**Non serve** creare un'Automation dell'agente se il PC deve restare la sorgente dati: l'Automation gira in cloud e non vede il tuo PostgreSQL locale senza tunnel.

### Se vuoi comunque un'Automation (solo cloud)

Utile solo se:

- importi direttamente sul DB cloud, oppure
- il tuo PC espone Postgres via tunnel e l'agent ha `DATABASE_SOURCE_URL` raggiungibile

Prompt esempio per Automation:

> Ogni giorno alle 09:00 esegui `python3 -m src.jobs.daily_pipeline` nel repo tennis_oracle. Verifica che `properties/config.env` abbia le URL DB corrette e logga l'esito.

## Test manuale

```bash
# Solo import locale
python3 -m src.service.import_fixtures

# Import + sync cloud
python3 -m src.jobs.daily_pipeline

# Solo import, senza cloud
python3 -m src.jobs.daily_pipeline --no-sync
```
