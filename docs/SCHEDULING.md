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

## Scheduler report dedicato (08:00 + lunedì 10:00)

Il servizio persistente `backend.src.jobs.run_report_scheduler` è separato
dall'API e usa il fuso `Europe/Rome`:

1. ogni giorno alle **08:00** esegue la stessa pipeline di **Aggiorna tutto**;
2. ogni lunedì alle **10:00** verifica la run giornaliera dello stesso lunedì;
3. avvia il walk-forward solo se la run giornaliera è esattamente `completed`;
4. avvia la calibrazione solo se il walk-forward è esattamente `completed`;
5. passa alla calibrazione il `walk_forward_run_id` appena generato;
6. invia sempre un riepilogo email, anche quando la cascata fallisce o viene saltata.

`completed_with_errors` non supera nessuno dei due gate. Il registro
`scheduled_report_job` assegna una chiave unica per job/data: se local, dev e
prod puntano accidentalmente allo stesso database, una sola origine acquisisce
lo slot. Nel registro e nell'email restano ambiente, nome sorgente, URL,
hostname e path runtime dell'origine vincente.

Configurazione non sensibile:

```env
GLOBAL_UPDATE_CRON_ENABLED=false
WALK_FORWARD_IN_GLOBAL_UPDATE=false

SCHEDULED_REPORTS_ENABLED=true
SCHEDULED_REPORTS_TIMEZONE=Europe/Rome
SCHEDULED_GLOBAL_UPDATE_TIME=08:00
SCHEDULED_WEEKLY_VALIDATION_DAY=0
SCHEDULED_WEEKLY_VALIDATION_TIME=10:00
SCHEDULED_REPORTS_POLL_SECONDS=30

# DEV Railway attualmente online
SCHEDULED_JOB_SOURCE_NAME=tennis-oracle-dev
SCHEDULED_JOB_SOURCE_URL=https://frontend-dev-dd35.up.railway.app/
SCHEDULED_JOB_SOURCE_PATH=/app

# TODO PROD: quando sara online, configurare:
# SCHEDULED_JOB_SOURCE_NAME=tennis-oracle-prod
# SCHEDULED_JOB_SOURCE_URL=https://<frontend-prod-url>/

REPORT_EMAIL_ENABLED=true
REPORT_EMAIL_TO=trottarosario@gmail.com
RESEND_API_BASE=https://api.resend.com
# DEV: valido se trottarosario@gmail.com e l'email dell'account Resend.
RESEND_FROM="Tennis Oracle <onboarding@resend.dev>"
RESEND_TIMEOUT_SECONDS=20
```

Secret obbligatorio, da impostare nel secret store dell'ambiente e mai nel
repository:

```env
RESEND_API_KEY=<chiave-API-Resend>
```

Resend riceve il messaggio e gli allegati tramite HTTPS. Il mittente
`onboarding@resend.dev` è utilizzabile soltanto in DEV e può inviare unicamente
all'indirizzo associato all'account Resend. Per PROD va verificato un dominio
proprio e impostato `RESEND_FROM` con un indirizzo di quel dominio:
<https://resend.com/docs/knowledge-base/403-error-resend-dev-domain>.

### Avvio Compose

Locale/prod-like:

```bash
docker compose --profile scheduler up --build -d scheduler
docker compose logs -f scheduler
```

Staging/dev isolato:

```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml \
  --env-file .env.staging --profile scheduler up --build -d scheduler
```

Produzione con overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --profile scheduler up --build -d scheduler
```

Su un provider che crea servizi direttamente dal `backend/Dockerfile`, crea un
servizio worker per ogni ambiente con start command:

```bash
python -m backend.src.jobs.run_report_scheduler
```

Dev e prod devono avere `SCHEDULED_JOB_SOURCE_NAME`, URL e secret distinti. Il
worker non espone una porta HTTP e deve avere restart automatico.

### Esecuzione controllata singola

I comandi seguenti eseguono job reali e rispettano la deduplica DB della data:

```bash
python -m backend.src.jobs.run_report_scheduler --run due
python -m backend.src.jobs.run_report_scheduler --run daily --date 2026-08-31
python -m backend.src.jobs.run_report_scheduler --run weekly --date 2026-08-31
```

Con `REPORT_EMAIL_ENABLED=false` il job viene eseguito e registrato, ma l'email
risulta `disabled`. Il worker persistente rifiuta invece l'avvio quando l'email
è abilitata ma mancano destinatario, `RESEND_API_KEY` o mittente Resend.

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

## Schedine stabili, live score e recap finale

Il pool delle schedine e' append-only fino a `BETTING_SLIP_POOL_CLOSE_TIME`
(default `10:00`, timezone `BETTING_SLIP_TIMEZONE=Europe/Rome`). Dopo la soglia
`betting_slip_day.pool_locked_at` impedisce definitivamente nuove pick; polling
live e settlement continuano senza rigenerare le schedine.

```env
BETTING_SLIP_TIMEZONE=Europe/Rome
BETTING_SLIP_POOL_CLOSE_TIME=10:00
BETTING_SLIP_LIVE_POLL_ENABLED=true
BETTING_SLIP_LIVE_POLL_INTERVAL_SECONDS=180
BETTING_SLIP_RECAP_ENABLED=true
BETTING_SLIP_RECAP_TIME=23:30
BETTING_SLIP_RECAP_STAKE=10.0
```

I job sono single-pass e idempotenti, adatti a cron/Task Scheduler:

```bash
python3 -m backend.src.jobs.run_betting_slip_live_poll --force --json
python3 -m backend.src.jobs.run_betting_slip_recap --force --json
```

Esempio cron: polling ogni 3 minuti e recap ogni 5 minuti nella finestra serale.
Il recap non invia finche' esiste una pick pending; la deduplica persistente
impedisce invii doppi quando la giornata diventa terminale.

```cron
*/3 * * * * cd /percorso/tennis_oracle && .venv/bin/python -m backend.src.jobs.run_betting_slip_live_poll
*/5 23,0-3 * * * cd /percorso/tennis_oracle && .venv/bin/python -m backend.src.jobs.run_betting_slip_recap
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

Job on-demand (o settimanale) che valuta il **mercato match-winner live**
(`ACTIVE_MATCH_WINNER_VERSIONS`, oggi `v4`) con fold temporali expanding/rolling.
Passa `--versions` esplicitamente per includere tag archiviati (v1–v3).
**Non** sovrascrive `baseline_*_metrics.json`,
**non** sostituisce il modello pubblico e **non** mescola i risultati con le
metriche live. L’aggiornamento globale include sempre una fase osservabile
(`summary.walk_forward`); l’esecuzione completa nel daily job resta opt-in via
`WALK_FORWARD_IN_GLOBAL_UPDATE=true`.

```bash
# Dry-run (calcola + JSON report, senza persistenza DB)
python3 -m backend.src.jobs.run_walk_forward --dry-run

# Esegue e persiste run/fold (default: solo live match-winner)
python3 -m backend.src.jobs.run_walk_forward

# Rolling su subset (archivio opt-in)
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

## Closing odds (job dedicato pre-kickoff)

L’import giornaliero cattura `opening`/`observed` e, a partita live, può etichettare come `closing` l’**ultimo** observed pre-kickoff (`seal_closing_from_last_prematch`). Da solo non è un true closing di mercato affidabile senza polling frequente (vedi analisi impatto sotto): da qui il job dedicato **`run_closing_odds_capture`**.

### Cosa fa

Ogni esecuzione è **un singolo passaggio** (nessun loop/sleep interno): trova le partite in `next_fixture` il cui orario di inizio (`event_date`/`event_time`, fuso Europe/Rome) cade entro `--window-minutes` da adesso (default `CLOSING_ODDS_CAPTURE_WINDOW_MINUTES`), richiede quote fresche al provider (`get_odds`) e le scrive **direttamente** con `snapshot_type=closing`. Partite senza `event_time` noto sono escluse (un orario sconosciuto non deve mai sembrare "imminente").

Eseguendolo di frequente (cron ogni 1–5 minuti) durante la finestra pre-partita si accumulano più righe `closing` per fixture/bookmaker: `_resolve_clv` (in `published_live_stats.py`) sceglie già quella con `captured_at` più recente per bookmaker, quindi nessuna modifica lato consumer è necessaria.

```bash
# Dry-run: elenca solo le fixture attualmente in finestra, nessuna chiamata API/scrittura
python3 -m backend.src.jobs.run_closing_odds_capture --dry-run

# Esecuzione singola (rispetta CLOSING_ODDS_JOB_ENABLED)
python3 -m backend.src.jobs.run_closing_odds_capture

# Forza l'esecuzione anche con CLOSING_ODDS_JOB_ENABLED=false (test manuale)
python3 -m backend.src.jobs.run_closing_odds_capture --force --json

# Finestra personalizzata (minuti prima del kickoff)
python3 -m backend.src.jobs.run_closing_odds_capture --window-minutes 45
```

Flag utili: `--window-minutes`, `--dry-run`, `--force`, `--json`. Exit code: `0` ok (anche a zero candidate), `1` se almeno una fixture ha fallito la cattura (le altre non sono bloccate: isolamento per-fixture).

### Configurazione

```env
# Disabilitato di default: abilita solo insieme a un cron/Task Scheduler frequente.
CLOSING_ODDS_JOB_ENABLED=false
CLOSING_ODDS_CAPTURE_WINDOW_MINUTES=60
```

### Cron (ogni 2 minuti, tutti i giorni)

```cron
*/2 * * * * cd /percorso/tennis_oracle && .venv/bin/python -m backend.src.jobs.run_closing_odds_capture
```

Windows Task Scheduler: trigger ripetuto ogni 2 minuti, programma `python`, argomenti
`-m backend.src.jobs.run_closing_odds_capture`, cartella iniziale la root del repository.

Nota: senza un cron/scheduler frequente configurato, lasciare `CLOSING_ODDS_JOB_ENABLED=false`
(il default) — un'esecuzione isolata o rara catturerebbe solo le fixture che casualmente si
trovano in finestra in quel momento, senza la copertura "densa" che giustifica il job.

### Impatto misurato sulla copertura CLV (2026-08-10, prima del job dedicato)

Analisi one-off sul DB locale (92 tip pubblicati, 22 lug – 10 ago 2026, `settle_published_tips`):

| Metrica | Valore |
|---|---|
| Tip pubblicati (ultima versione) | 92 |
| Con `clv_pct` disponibile | **9 / 92 (9.8%)** |
| Con `clv_prob_delta_pct` (no-vig) disponibile | **0 / 92 (0%)** |
| Copertura per settimana | sett.30: 7/25 · sett.31: **0/48** · sett.32: 2/18 |

La copertura non era solo bassa, era **irregolare** (una settimana intera a 0/48): confermava che il meccanismo opportunistico da solo non produce un flusso costante di `closing` utilizzabile, indipendentemente da quanto tempo passa. Restava **bloccante** per qualunque idea ML che usi il CLV come target o feature (vedi anche gli esperimenti v4 in `backend/src/app/ml/training/`): il campione utile sarebbe rimasto troppo piccolo (singole unità/settimana) per un training o anche solo per statistiche descrittive robuste (il progetto usa già `min_segment_samples=30` come soglia minima per un solo segmento ROI).

**Prossimo passo per riprendere l'idea "target CLV"**: abilitare `CLOSING_ODDS_JOB_ENABLED=true` con il cron sopra, lasciar accumulare dati per settimane/mesi, solo dopo rivalutare volume e fattibilità con `check_clv_ml_readiness.py`.


