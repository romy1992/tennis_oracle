# Scheduling giornaliero (produzione)

## Orchestratore unico

Il job di produzione e il pulsante UI **Aggiorna tutto** usano lo **stesso orchestratore**:
`backend.src.app.services.global_update` (`start_global_update` / `_execute_global_update`).

Entrypoint CLI consigliato:

```bash
python3 -m backend.src.jobs.run_global_update --days-forward 10
```

Compatibilità: `python -m backend.src.jobs.daily_pipeline` delega allo stesso job
(con `force=True` per preservare il comportamento “esegui sempre” degli script legacy).

### Cosa fa la pipeline

1. **Lock distribuito** su tabella `pipeline_lock` (niente esecuzioni concorrenti)
2. **Import fixtures** disputate
3. **Import prossime partite** (`next_fixture`)
4. **Previsioni + schedine + pubblicazione live** per **tutte** le combo con artefatto `.pkl`
5. **Sync cloud** opzionale (`--sync-cloud` / `SYNC_CLOUD=true`)
6. **Walk-forward osservabile** (`summary.walk_forward`; esecuzione completa solo se `WALK_FORWARD_IN_GLOBAL_UPDATE=true`)
7. **Report finale** in `global_update_run.report_json` (stesso report della UI)

### Affidabilità

| Funzione | Comportamento |
|----------|----------------|
| Lock DB | `pipeline_lock` con lease + heartbeat |
| Idempotenza | Skip se già `completed` oggi (salvo `--force`) |
| Retry | `GLOBAL_UPDATE_STEP_RETRIES` + backoff |
| Timeout step | `GLOBAL_UPDATE_STEP_TIMEOUT_SECONDS` |
| Stato / durata | `global_update_run` + `phases_json` + item per combo |
| Crash | run → `interrupted`; job riprende con auto-resume / `--resume` |
| Cancel | flag DB `cancel_requested` (UI o API); cooperativa |
| Exit code | `0` ok, `1` with errors, `2` failed/interrupted, `3` cancelled, `4` busy, `5` config |

Scheduler in-app (`GLOBAL_UPDATE_CRON_ENABLED`) resta **opzionale** e va tenuto `false` in produzione multi-replica: usa cron host o `docker compose --profile jobs`.

## Configurazione

`backend/properties/config.env` (vedi anche `config.env.example`):

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tennis_db
DATABASE_SOURCE_URL=postgresql://postgres:postgres@localhost:5432/tennis_db
DATABASE_TARGET_URL=postgresql://postgres:postgres@<host-cloud>:5432/tennis_db
SYNC_CLOUD=true

GLOBAL_UPDATE_CRON_ENABLED=false
GLOBAL_UPDATE_ALLOW_CONCURRENT_RUNS=false
GLOBAL_UPDATE_STEP_RETRIES=2
GLOBAL_UPDATE_RETRY_BACKOFF_SECONDS=5
GLOBAL_UPDATE_STEP_TIMEOUT_SECONDS=3600
GLOBAL_UPDATE_LOCK_TTL_SECONDS=21600
```

Applica le migrazioni (inclusa `0016_pipeline_reliability`):

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
```

## Docker one-shot

```bash
docker compose --profile jobs run --rm job
```

Il servizio `job` esegue `backend.src.jobs.run_global_update`.

## Cron sul PC

### Linux / macOS

```bash
mkdir -p /percorso/tennis_oracle/backend/logs
chmod +x /percorso/tennis_oracle/backend/scripts/run_daily_job.sh
crontab -e
```

```cron
0 9 * * * /percorso/tennis_oracle/backend/scripts/run_daily_job.sh
```

### Windows (Task Scheduler)

1. Trigger giornaliero (es. 09:00)
2. Programma: `...\backend\scripts\run_daily_job.bat`
3. Cartella iniziale: root del repository

## Comandi utili

```bash
# Run standard (skip se già completata oggi; auto-resume se interrupted)
python3 -m backend.src.jobs.run_global_update --days-forward 10

# Forza nuova run
python3 -m backend.src.jobs.run_global_update --force

# Con sync cloud
python3 -m backend.src.jobs.run_global_update --sync-cloud

# Riprendi dal primo step/item fallito
python3 -m backend.src.jobs.run_global_update --resume
python3 -m backend.src.jobs.run_global_update --resume-run-id 42

# Senza auto-resume
python3 -m backend.src.jobs.run_global_update --no-auto-resume --force
```

Il pulsante UI continua a chiamare `POST /api/global-update` (stesso orchestratore, thread in-process, senza sync cloud di default).

## Policy previsioni

Una riga per `event_key + model_version + model_name`. Le righe future/non risolte
vengono aggiornate; le righe già valutabili con `actual_winner` non vengono sovrascritte.

## Controlli operativi post-job

Dopo il job giornaliero puoi eseguire i check di monitoraggio (import fresco,
presenza pronostici, durata anomala, esito ultima run) e inviare alert admin:

```bash
python3 -m backend.src.jobs.run_ops_checks --alert
```

Exit code: `0` ok, `1` warning, `2` critical. Configurazione e canali alert:
[MONITORING.md](MONITORING.md).

## Notifiche Telegram utente (push)

Dopo un aggiornamento globale riuscito puoi inviare push configurabili agli utenti
beta `active` (con `chat_id` da `/start`, preferenze `/notifiche`, non sospesi):

```bash
# Dry-run (nessuna chiamata Bot API)
python3 -m backend.src.jobs.run_telegram_notifications --dry-run

# Pronostici oggi + giorno vuoto + riepilogo risultati di ieri
python3 -m backend.src.jobs.run_telegram_notifications

# Solo risultati di una data
python3 -m backend.src.jobs.run_telegram_notifications --kinds results --results-date 2026-07-26
```

Flag utili: `--force` (ignora dedupe già inviato), `--json`, `--model-version` /
`--model-name`. Richiede `TELEGRAM_NOTIFICATIONS_ENABLED=true` e `TELEGRAM_BOT_TOKEN`.
Dedupe e log consegna/errore in tabella `telegram_notification_delivery` (migrazione `0018`).
Rate limit outbound: `TELEGRAM_NOTIFY_MIN_INTERVAL_SECONDS` + retry su 429/5xx.

Cron esempio (dopo il job delle 09:00):

```cron
15 9 * * * cd /percorso/tennis_oracle && .venv/bin/python -m backend.src.jobs.run_telegram_notifications
```

Gli alert admin per pipeline fallita restano su `OPS_ALERTS_ENABLED` +
`TELEGRAM_ADMIN_CHAT_ID` (vedi [MONITORING.md](MONITORING.md)); non usano il ledger utente.

## Report settimanale beta

Ogni lunedì (o on-demand) genera uno snapshot KPI della settimana ISO precedente
(lun–dom): utenti totali/attivi/nuovi, retention W1, comandi bot, tip pubblicati,
ROI/yield/drawdown live, errori pipeline, notifiche fallite, feedback, confronto
WoW. Persistenza in `weekly_beta_report` (migrazione `0020`); riepilogo su
`TELEGRAM_ADMIN_CHAT_ID` se `WEEKLY_BETA_REPORT_TELEGRAM_ENABLED=true`.

```bash
# Dry-run (calcola, non salva / non invia)
python3 -m backend.src.jobs.run_weekly_beta_report --dry-run

# Genera settimana precedente + Telegram admin
python3 -m backend.src.jobs.run_weekly_beta_report

# Forza ricalcolo di una settimana (lunedì ISO)
python3 -m backend.src.jobs.run_weekly_beta_report --week-start 2026-07-13 --force
```

Flag utili: `--no-telegram`, `--json`. Visibile in dashboard: **Report settimanale beta**.

Cron esempio (lunedì 08:30 Rome):

```cron
30 8 * * 1 cd /percorso/tennis_oracle && .venv/bin/python -m backend.src.jobs.run_weekly_beta_report
```

## Walk-forward (validazione temporale)

Job on-demand (o settimanale) che valuta tutte le versioni/modelli con fold
temporali expanding/rolling. **Non** sovrascrive `baseline_*_metrics.json`,
**non** sostituisce il modello pubblico e **non** mescola i risultati con le
metriche live. L’aggiornamento globale include sempre una fase osservabile
(`summary.walk_forward`); l’esecuzione completa nel daily job resta opt-in via
`WALK_FORWARD_IN_GLOBAL_UPDATE=true`.

```bash
# Dry-run (calcola + JSON report, senza persistenza DB)
python3 -m backend.src.jobs.run_walk_forward --dry-run

# Esegue e persiste run/fold
python3 -m backend.src.jobs.run_walk_forward

# Rolling su subset versioni
python3 -m backend.src.jobs.run_walk_forward --mode rolling --versions v2,v3
```

Flag utili: `--initial-train-days`, `--test-days`, `--step-days`, `--embargo-days`,
`--min-train-rows`, `--min-test-rows`, `--json`. Visibile in dashboard:
**Walk-forward** (sezione BACKTEST / OPS).

## Calibrazione probabilità (ML-02)

Job opzionale che analizza la **calibrazione** delle probabilità usando solo dati
out-of-sample prodotti dal walk-forward. Per ogni fold, i calibratori (Platt /
isotonic) sono addestrati solo sul passato rispetto al periodo valutato.

```bash
# Dry-run (calcola + JSON report, senza persistenza DB)
python3 -m backend.src.jobs.run_calibration --dry-run

# Esegue e persiste run/risultati + artefatti versionati
python3 -m backend.src.jobs.run_calibration

# Subset versioni
python3 -m backend.src.jobs.run_calibration --versions v2,v3
```

Flag utili: `--n-bins`, `--min-bin-samples`, `--min-calibrator-train-samples`,
`--methods raw,platt,isotonic`, più i parametri finestra walk-forward
(`--mode`, `--initial-train-days`, …). Visibile in dashboard: **Calibrazione**
(sezione BACKTEST / OPS). **Non** modifica il modello pubblico né le previsioni live.

## Backup PostgreSQL

Dump logico pianificato (timestamp, compressione custom, retention, GPG opzionale,
alert su errore). Dettaglio e disaster recovery: [BACKUP_DR.md](BACKUP_DR.md).

```bash
# Manuale
python3 -m backend.src.jobs.run_db_backup --alert

# Cron (es. 03:30)
30 3 * * * /percorso/tennis_oracle/backend/scripts/backup_postgres.sh
```

Windows Task Scheduler: `backend\scripts\backup_postgres.bat`.

Restore di prova **senza** toccare il DB reale:

```bash
python3 -m backend.src.jobs.run_db_restore --archive backups/<file>.dump --mode dry-run
python3 -m backend.src.jobs.run_db_restore --archive backups/<file>.dump --mode test
```

## Closing odds (job futuro)

L’import corrente cattura `opening`/`observed` e, a partita live, può etichettare come `closing` l’**ultimo** observed pre-kickoff (`seal_closing_from_last_prematch`). Non è un true closing di mercato affidabile senza polling frequente.

**Job futuro consigliato:** cattura dedicata della quota nell’intervallo immediatamente precedente l’inizio partita (es. ogni 1–5 minuti nelle ultime 30–60 minuti), scrivendo `snapshot_type=closing` solo con `captured_at` pre-kickoff.
