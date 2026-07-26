# Backup e disaster recovery (PostgreSQL)

Procedura automatizzata di **backup logico** (`pg_dump` formato custom) e **ripristino** per `tennis_oracle`. Nessuna password è hard-coded negli script: usa `DATABASE_URL` oppure le variabili libpq / Compose (`PG*` / `POSTGRES_*`).

| Artefatto | Ruolo |
|-----------|--------|
| `backend/src/service/postgres_backup.py` | Logica: dump, checksum SHA-256, retention, GPG, restore |
| `python -m backend.src.jobs.run_db_backup` | CLI backup + alert su errore |
| `python -m backend.src.jobs.run_db_restore` | CLI restore (`dry-run` / `test` / `overwrite`) |
| `backend/scripts/backup_postgres.sh` / `.bat` | Wrapper cron (abilita `--alert`) |
| `backend/scripts/restore_postgres.sh` / `.bat` | Wrapper restore |

I file finiscono in `backups/` (già in `.gitignore` / `.dockerignore`). Non committare dump, checksum o chiavi GPG.

---

## Prerequisiti

Sul host (o nel container da cui lanci lo script) devono essere disponibili:

- `pg_dump`, `pg_restore`, `psql` (client PostgreSQL 16 allineato al server)
- `python3` con le dipendenze backend
- opzionale: `gpg` se `BACKUP_ENCRYPT=true`

Connessione: stesso database usato dall’API (`DATABASE_URL` in root `.env` o `backend/properties/config.env`).

---

## Variabili d’ambiente

```env
# Directory dump (relativa alla root del repo se non assoluta)
BACKUP_DIR=backups

# Elimina dump tennis_oracle_* più vecchi di N giorni (0 = non eliminare)
BACKUP_RETENTION_DAYS=7

# Cifratura predisposta (default off). Richiede gpg + uno dei due:
BACKUP_ENCRYPT=false
BACKUP_GPG_RECIPIENT=
# oppure passphrase in un file locale (non nel repo):
BACKUP_GPG_PASSPHRASE_FILE=

# Alert su fallimento (stessi canali di docs/MONITORING.md)
OPS_ALERTS_ENABLED=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=
OPS_ALERT_WEBHOOK_URL=
```

Le password restano in `DATABASE_URL` / `PGPASSWORD` / `POSTGRES_PASSWORD` gestiti fuori dal VCS.

---

## Backup

### Esecuzione manuale

Dalla **root del repository**:

```bash
python3 -m backend.src.jobs.run_db_backup
# oppure
./backend/scripts/backup_postgres.sh
```

Windows (Task Scheduler / cmd):

```bat
backend\scripts\backup_postgres.bat
```

### Cosa produce

- Archivi: `backups/<db>_YYYYMMDD_HHMMSS.dump` (formato custom compresso)
- Se cifratura attiva: `….dump.gpg` (il `.dump` in chiaro viene rimosso)
- Checksum: `….sha256` (verificato subito dopo la scrittura)
- Integrità: `pg_restore --list` sul dump (per `.gpg`: decrypt di prova + checksum)

### Exit code

| Code | Significato |
|------|-------------|
| `0` | OK |
| `1` | OK con warning |
| `2` | Errore (con `--alert` / wrapper `.sh`/`.bat`: notifica admin) |

### Cron consigliato

Vedi anche [SCHEDULING.md](SCHEDULING.md). Esempio Linux (03:30, dopo il job dati se preferisci invertire l’ordine):

```cron
30 3 * * * /percorso/tennis_oracle/backend/scripts/backup_postgres.sh
```

Conserva una copia **fuori dalla macchina** (object storage, altro host, volume snapshot). La retention locale non sostituisce un offsite.

### Cifratura (predisposta)

1. Installa `gpg` e crea una chiave (o usa una passphrase in file con permessi `600`).
2. Imposta `BACKUP_ENCRYPT=true` e `BACKUP_GPG_RECIPIENT=<id>` **oppure** `BACKUP_GPG_PASSPHRASE_FILE=/path/segreto`.
3. Esegui un backup di prova e verifica che esista solo `*.dump.gpg` + `*.sha256`.

Senza recipient/passphrase file lo script **fallisce** (exit `2`) invece di lasciare dump in chiaro per errore di config.

---

## Restore

### Modalità sicure (non sovrascrivono il DB reale)

**1. Dry-run** — solo checksum + elenco contenuto archivio:

```bash
python3 -m backend.src.jobs.run_db_restore \
  --archive backups/tennis_db_20260726_013000.dump \
  --mode dry-run
```

**2. Test restore** — crea/riempie un database alternativo (default `{source}_restore_test`):

```bash
python3 -m backend.src.jobs.run_db_restore \
  --archive backups/tennis_db_20260726_013000.dump \
  --mode test
# oppure nome esplicito:
python3 -m backend.src.jobs.run_db_restore \
  --archive backups/tennis_db_20260726_013000.dump \
  --mode test --target-db tennis_db_restore_test
```

Poi verifica con `psql` sul DB di test (conteggi tabelle, smoke API puntando temporaneamente `DATABASE_URL` a quel DB). Elimina il DB di test quando hai finito.

### Disaster recovery (sovrascrive il DB sorgente)

Operazione **distruttiva**: termina le sessioni, drop/create del database indicato da `DATABASE_URL`, poi `pg_restore`.

1. Ferma API / job / bot che usano quel DB (`docker compose stop api bot job` o equivalenti).
2. Scegli l’archivio (preferisci offsite se il disco locale è compromesso).
3. Esegui dry-run, poi test restore se il tempo lo consente.
4. Solo dopo conferma:

```bash
python3 -m backend.src.jobs.run_db_restore \
  --archive backups/tennis_db_YYYYMMDD_HHMMSS.dump \
  --mode overwrite \
  --overwrite-source \
  --yes
```

5. `alembic upgrade head` solo se il dump è più vecchio dello schema atteso (di solito lo schema è già nel dump).
6. Riavvia i servizi e lancia `backend/scripts/smoke_check.py` + `python -m backend.src.jobs.run_ops_checks`.

Per archivi `.gpg` simmetrici passa `--gpg-passphrase-file` (o la stessa env `BACKUP_GPG_PASSPHRASE_FILE`).

---

## Runbook disaster recovery (checklist)

1. [ ] Dichiarare l’incidente e congelare scritture (stop API/job).
2. [ ] Individuare l’ultimo backup integro (locale + offsite); verificare `.sha256`.
3. [ ] `run_db_restore --mode dry-run`.
4. [ ] Se possibile: `--mode test` e smoke sul DB di prova.
5. [ ] `--mode overwrite --overwrite-source --yes` sul DB reale.
6. [ ] Verificare readiness (`GET /ready`), ops checks, login admin, un flusso Telegram/API critico.
7. [ ] Documentare ora UTC del restore, nome file, e cause.
8. [ ] Ripristinare il cron di backup e fare un **nuovo** backup post-recovery.

Staging: prima di migrate rischiosi usa lo stesso backup (vedi checklist in [STAGING.md](STAGING.md)).

---

## Limitazioni

- È un backup **logico**, non un PITR / WAL continuous archiving. Per RPO più stretti valuta snapshot volume + WAL su Postgres gestito.
- Ruoli/global objects fuori dal DB non sono necessariamente nel dump custom di un singolo database.
- `pg_restore` può uscire con codice `1` per warning (ruoli mancanti, ecc.): lo script lo tratta come warning (exit `1`), non come fallimento duro.
- Non sostituisce il sync cloud (`database_migrator` / `SYNC_CLOUD`): quello copia tabelle live, non è un archivio DR.
