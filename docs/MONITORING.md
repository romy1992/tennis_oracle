# Monitoring operativo (produzione)

Stack di osservabilità **senza vincolo a un unico provider**: logging strutturato, correlation ID, metriche scrapeabili, error tracking configurabile, alert admin (Telegram / webhook) e controlli operativi sulla pipeline.

Dettaglio implementativo: pacchetto `backend/src/app/observability/`.

---

## Componenti

| Pezzo | Ruolo | Provider / formato |
|-------|--------|-------------------|
| Logging | Log applicativi con redazione secret | `LOG_FORMAT=text` o `json` |
| Correlation ID | Traccia richiesta/job | header `X-Correlation-ID` / `X-Request-ID` |
| Metriche | Contatori e latenze API / bot / pipeline | `none` \| `memory` \| `prometheus` |
| Error tracking | Eccezioni e messaggi | `none` \| `logging` \| `sentry` \| `webhook` |
| Alert | Notifiche admin | Telegram Bot API + webhook opzionale |
| Health | Liveness / readiness / dipendenze | `GET /health`, `/ready`, `/deps` |
| Ops checks | Import, pronostici, durata | `GET /api/ops/checks`, job CLI |

I secret non finiscono nei log: filtro su `observability.logging` + `utility/sensitive_data`.

---

## Endpoint

| Metodo | Path | Auth | Note |
|--------|------|------|------|
| GET | `/health` | pubblica | Liveness (processo up) |
| GET | `/ready` | pubblica | Readiness (DB); **503** se DB giù |
| GET | `/deps` | pubblica | Stato dipendenze (DB, canali monitoring); **nessun secret** |
| GET | `/metrics` | pubblica* | Prometheus text (`text/plain`) se abilitato |
| GET | `/metrics.json` | pubblica* | Snapshot JSON in-process |
| GET | `/api/ops/checks` | admin JWT | Controlli import / pronostici / durata |
| GET | `/api/ops/checks?alert=true` | admin JWT | Come sopra + invio alert |

\* Disabilita con `METRICS_ENDPOINT_ENABLED=false` o `METRICS_PROVIDER=none` (risposta 404).

Probe e scrape sono esclusi dal rate limit (`/health`, `/ready`, `/deps`, `/metrics`).

---

## Variabili d’ambiente

Aggiungi in `backend/properties/config.env` (modello: `config.env.example`) e/o `.env` root:

```env
# Logging: text (default) | json (consigliato in prod / aggregatori)
LOG_FORMAT=json

# Metriche: none | memory | prometheus
METRICS_PROVIDER=prometheus
METRICS_ENDPOINT_ENABLED=true

# Error tracking: none | logging | sentry | webhook
ERROR_TRACKING_PROVIDER=logging
# Solo se provider=sentry (richiede pacchetto opzionale sentry-sdk)
ERROR_TRACKING_DSN=
# Solo se provider=webhook (URL generico, qualsiasi ingest)
ERROR_TRACKING_WEBHOOK_URL=

# Alert amministrativi (fail-open: errori di invio non rompono la pipeline)
OPS_ALERTS_ENABLED=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=
OPS_ALERT_WEBHOOK_URL=
OPS_ALERT_COOLDOWN_SECONDS=300

# Soglie controlli operativi
OPS_IMPORT_MAX_AGE_HOURS=36
OPS_PREDICTIONS_LOOKBACK_HOURS=36
OPS_PIPELINE_MAX_DURATION_SECONDS=7200
```

Note:

- `TELEGRAM_BOT_TOKEN` può essere lo stesso del bot utenti; `TELEGRAM_ADMIN_CHAT_ID` è l’ID chat/canale admin (non un token).
- `sentry-sdk` **non** è in `requirements.txt`: installalo solo se scegli Sentry (`pip install sentry-sdk`).
- Webhook di error tracking e alert accettano un POST JSON generico (compatibile con molti ingest / relay).

---

## Configurazione consigliata per produzione

1. `LOG_FORMAT=json` e raccolta log da stdout (Docker / journald / agent).
2. `METRICS_PROVIDER=prometheus` + scrape di `GET /metrics` (Prometheus, Grafana Agent, Datadog agent, …).
3. `ERROR_TRACKING_PROVIDER=logging` come baseline; oppure `webhook` / `sentry` se hai già un backend errori.
4. `OPS_ALERTS_ENABLED=true` con `TELEGRAM_ADMIN_CHAT_ID` (e token) **oppure** `OPS_ALERT_WEBHOOK_URL`.
5. Probe orchestrator: liveness → `/health`, readiness → `/ready`.
6. Dopo il job giornaliero (o con cron dedicato), esegui i controlli:

```bash
python -m backend.src.jobs.run_ops_checks --alert
```

Exit code: `0` ok, `1` warning, `2` critical.

Esempio cron (dopo il job delle 09:00):

```cron
30 9 * * * /percorso/tennis_oracle/backend/scripts/run_ops_checks.sh
```

(oppure chiama direttamente il modulo Python come sopra).

---

## Cosa viene controllato / alertato

| Controllo | Condizione | Severità tipica |
|-----------|------------|-----------------|
| `import_freshness` | Nessun import next_fixture o più vecchio di `OPS_IMPORT_MAX_AGE_HOURS` | warning / critical |
| `predictions_present` | Zero `MatchPrediction` nelle ultime `OPS_PREDICTIONS_LOOKBACK_HOURS` | critical |
| `pipeline_duration` | Run con durata > `OPS_PIPELINE_MAX_DURATION_SECONDS` | warning |
| `latest_run_outcome` | Ultima run `failed` / `interrupted` / `completed_with_errors` | critical / warning |

Inoltre, a fine **global update**, vengono emesse metriche `pipeline_*` e, se lo stato non è ok (o la durata è anomala), un alert admin (con cooldown).

Il bot Telegram incrementa `telegram_bot_events_total` (success/failure per action).

---

## Correlation ID

- Se il client invia `X-Correlation-ID` o `X-Request-ID`, viene riusato.
- Altrimenti l’API ne genera uno (UUID hex) e lo rimette in risposta.
- Compare nei log JSON (`correlation_id`) e negli alert.
- I job CLI impostano un id del tipo `job-global-update-<pid>` / `ops-checks-<pid>`.

---

## Docker / staging

- Healthcheck Compose resta su `/health` (liveness).
- In staging puoi smoke-testare anche `/ready` e `/deps` (vedi `docs/STAGING.md` e `backend/scripts/smoke_check.py`).
- Non committare DSN, token o chat id reali: solo placeholder negli example file.

---

## Sicurezza

- `/metrics` espone cardinalità bassa (path normalizzati, niente query/body).
- `/deps` e i log non includono password, JWT, API key o bot token in chiaro.
- Gli alert Telegram usano l’API ufficiale `sendMessage`; errori di rete vengono loggati e ignorati (fail-open).
