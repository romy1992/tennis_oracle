# Implementation Log — Tennis Oracle

Branch `cursor/platform-audit-evolution-e436` (base `origin/main` = `4bd7281`).
Nessun deploy, nessuna modifica al DB, nessuna chiamata a provider a pagamento
(test solo con mock/fixture), artefatti in `backend/data/models` invariati,
probabilita' pubblicate e soglie invariate. Modifiche API solo additive.

Storia: 6 commit dell'11/11/2026 (`8d9ca20`..`56ac58a`) + 1 commit del 14/11
(`5515aec`) non verificati fino in fondo; verificati, corretti e completati il
17/11/2026 (commit da `2da4346` in poi). Numeri dei test in `TEST_REPORT.md`.

## 1. Client API-Tennis (`backend/src/utility/request_api.py`, `resilience.py`)

| commit | data | cosa |
|---|---|---|
| `8d9ca20` | 11/11 | retry con backoff esponenziale + jitter, circuit breaker di processo, metriche |
| `5515aec` | 14/11 | budget di tempo per chiamata; breaker creato/ricreato sotto lock |
| `2da4346` | 17/11 | **corretto**: la chiave API finiva nei traceback (vedi sotto) |
| `9028443` | 17/11 | `API_TENNIS_RETRY_BUDGET_SECONDS` documentata negli esempi e nella guida |
| `41b6ab9` | 17/11 | test di concorrenza: 16 thread, breaker aperto una sola volta |

Parametri (default nel codice, tutti sovrascrivibili via env):

| variabile | default | riferimento |
|---|---|---|
| `API_TENNIS_TIMEOUT` | 30 s (invariato, errore tipizzato `ApiTennisTimeoutError` invariato) | `request_api.py:39` |
| `API_TENNIS_MAX_RETRIES` | 2 tentativi extra | `request_api.py:51` |
| `API_TENNIS_RETRY_BACKOFF_SECONDS` / `_MAX_SECONDS` | 0.5 / 8 ("equal jitter": meta' fissa, meta' casuale) | `request_api.py:52-53`, `resilience.py:23-38` |
| `API_TENNIS_RETRY_BUDGET_SECONDS` | 2 × timeout = 60 s | `request_api.py:230`, `:321` |
| `API_TENNIS_CIRCUIT_FAILURE_THRESHOLD` | 5 tentativi falliti consecutivi (0 = disattivato) | `request_api.py:59` |
| `API_TENNIS_CIRCUIT_RECOVERY_SECONDS` | 60 s, poi una sola probe half-open | `request_api.py:60`, `resilience.py:100` |

- Retry solo su timeout, errori di connessione/rete e HTTP 429/5xx
  (`request_api.py:208-209`). Mai su 4xx, JSON non valido o errore dichiarato
  dal provider in `result` (test dedicati).
- Un 4xx non apre il breaker: il provider ha risposto (`request_api.py:297-299`).
- Budget: un nuovo tentativo parte solo se `trascorso + attesa + timeout <= budget`.
  Con i default un timeout pieno (30 s) non viene ritentato, quindi la latenza
  peggiore di una chiamata che va in timeout resta ~30 s come su main; gli
  errori rapidi vengono ritentati (attese 0.25-0.5 s e 0.5-1 s). Limite residuo:
  `timeout` di requests vale per connessione/lettura, non per l'intera risposta
  (come su main).
- Job lunghi (es. `import_next_fixtures`, una `get_odds` per partita): con
  provider giu' il breaker si apre dopo 5 tentativi falliti e le chiamate
  successive falliscono subito (`ApiTennisCircuitOpenError`, sottoclasse di
  `ApiTennisNetworkError`) invece di attendere un timeout ciascuna.
- Thread-safety: breaker con lock interno (`resilience.py:62`), singleton di
  processo creato sotto `_breaker_lock` (`request_api.py:168`); metriche nel
  registro con lock. Stato non condiviso tra processi/worker (dichiarato).
- Metriche: `api_tennis_requests_total{method,outcome}`,
  `api_tennis_retries_total{method,reason}`,
  `api_tennis_request_duration_seconds{method}`,
  `api_tennis_circuit_breaker_transitions_total{state}` (`request_api.py:62-65`).
- **Difetto trovato e corretto (`2da4346`)**: requests/urllib3 mettono l'URL
  completo (query string con `APIkey`) nel messaggio delle eccezioni di
  trasporto; il client le concatenava come `__cause__` (su main con
  `raise ... from exc`), quindi ogni `logger.exception` a valle (es.
  `global_update.py:444`) scriveva la chiave nei log. Dimostrato in locale con
  una chiave finta e una porta chiusa (nessuna rete esterna): prima del fix
  traceback e log contenevano la chiave, dopo no. Ora la causa e'
  `ApiTennisTransportCause` (`request_api.py:103-121`) con solo tipo e messaggio
  redatto. Tipi e messaggi degli errori sollevati invariati.

## 2. Import prossimi incontri (`backend/src/service/import_next_fixtures.py`) — `676175b`

- `fetch_odds_for_match(event_key, *, failures=None)` (`:387-405`): ritorno
  invariato (`dict | None`); il parametro opzionale distingue "errore del
  provider" da "nessuna quota". Chiamanti esistenti verificati:
  `prematch_odds_snapshots.py:949` (chiamata senza `failures`, invariata).
- Il riepilogo dell'import ha 3 chiavi additive: `odds_fetched`, `odds_empty`,
  `odds_fetch_errors` (`:470-472`). Compaiono in `next_fixtures_summary` di
  `POST /api/imports/refresh` (schema `RefreshMatchesResponse`, campo `dict`
  gia' esistente) e in `import` di `POST /api/matches/{event_key}/refresh`.
  Le quote salvate non vengono toccate quando la chiamata fallisce.
- `single_event_refresh.py` usa `_ingest_upcoming_payloads` con un
  `defaultdict(int)`: compatibile, `test_single_event_refresh.py` verde.

## 3. Stato di sufficienza dei dati (`data_quality`)

| commit | data | cosa |
|---|---|---|
| `183c4f4` | 11/11 | `data_sufficiency.py`, `data_quality` nel risultato di `predict_fixture`, `odds_captured_at`, policy feature mancanti |
| `2c2f8cd` | 17/11 | test: col default la probabilita' e' esattamente quella del riempimento storico con 0 |
| `797e880` | 17/11 | `data_quality` in lettura: feature ATP non disponibili sempre; storico giocatori opt-in |

Campi additivi (opzionali, nessuna rimozione/rinomina):

- `MatchPredictionRead.data_quality: dict | None` (`schemas/prediction.py:62`),
  valorizzato solo per le partite da giocare in `GET /api/next-fixtures/predictions`
  (`FixturesWithPredictionsPage.items[].prediction.data_quality`). Chiavi:
  `status` (`sufficient` / `limited` / `insufficient`), `reasons`,
  `systemic_gaps`, `details`, `evaluated`, `not_evaluated`.
- `NextFixtureWithPrediction.odds_captured_at: datetime | None`
  (`schemas/prediction.py:94`): ultima cattura quote match winner (UTC), `null`
  se non registrata.
- `predict_fixture(...)["data_quality"]` (dict interno, non persistito).
- Config: `MATCH_WINNER_MISSING_FEATURE_POLICY` (default `zero`,
  `config.py:172`), `PREDICTION_DATA_QUALITY_HISTORY_ENABLED` (default `false`,
  `config.py:180`).

Copertura:
- Giocatori senza storico / con poco storico (< 5 partite,
  `data_sufficiency.py:28`): motivi `player_N_no_history` / `player_N_low_history`,
  stato `limited`. In inferenza sempre; in lettura solo con
  `PREDICTION_DATA_QUALITY_HISTORY_ENABLED=true` (una query aggregata per
  pagina su `fixture`, che non ha indici sulle chiavi giocatore: latenza in
  produzione **non misurata**, per questo opt-in). Disattivato, `player_history`
  compare in `not_evaluated`.
- Feature ATP mancanti: le 13 colonne di arricchimento (eta', altezza, mano,
  `atp_surface`, `atp_tourney_level`, `atp_round`, `atp_best_of`,
  `atp_match_found`) non vengono mai costruite in serving: riportate in
  `systemic_gaps: ["enrichment_features_unavailable"]` e
  `details.unavailable_feature_columns`, senza abbassare lo stato (riguardano
  ogni partita). Nota: `ATP_DEFAULTS` (`predictor.py:373`) viene scritto sulla
  riga grezza ma eliminato da `_clean_features`; al modello arriva l'intero 0
  aggiunto da `fill_missing_feature_columns` (`predictor.py:577`), non i valori
  di `ATP_DEFAULTS` (es. `atp_best_of=3`). Verificato con l'artefatto v4.
- `blend_with_market` / `predicted_winner_market_probability` di main non
  toccati: `data_quality` e' solo descrittivo.

Policy feature mancanti: col default `zero` il comportamento e' identico a main
(test `test_default_policy_probability_is_exactly_the_legacy_integer_zero_fill`:
uguaglianza esatta con il riempimento storico sull'artefatto v4). `impute` e'
opt-in e cambierebbe le probabilita' di produzione: non attivato.

## 4. Benchmark walk-forward (`backend/src/app/ml/benchmarks/match_winner_walk_forward.py`)

| commit | data | cosa |
|---|---|---|
| `01b7fb0` | 11/11 | benchmark + report JSON |
| `180f653` | 17/11 | **corretto**: etichetta del circuito inferito calcolata con dati futuri; accuratezza nello skew; note di protocollo; report rigenerato; test di protocollo |
| `a25b162` | 17/11 | riepilogo leggibile `match_winner_walk_forward_benchmark.md` |

- Comando: `python -m backend.src.app.ml.benchmarks.match_winner_walk_forward`
  (offline, ~5 min su questa macchina). Scrive
  `backend/data/reports/benchmarks/match_winner_walk_forward_benchmark.json` e `.md`.
- Riproducibilita': rilanciato il 17/11 col codice di `01b7fb0` (invariato fino a `797e880`): 8708
  valori confrontati, unica differenza l'indentazione di una docstring
  (Python 3.13 vs 3.12). Dopo le correzioni, due esecuzioni consecutive
  identiche tranne il testo modificato tra le due.
- Leakage: fold trimestrali cronologici (train < inizio fold); imputer/scaler
  dentro la pipeline; Elo ricalcolato in ordine di data con aggiornamento dopo la
  predizione e batching per giorno; iperparametri Elo dinamico scelti sui 730
  giorni prima del primo fold; `atp_score`, `atp_minutes` e colonne di
  profitto/edge escluse (test sintetico in cui queste colonne rivelano il
  risultato: nessun modello le riceve). Audit indipendente delle colonne del
  dataset (H2H, forma, partite ultimi 14 giorni, giorni dall'ultima partita)
  ricalcolate solo da date precedenti: 0 discrepanze a parte il sentinel
  "nessuno storico" (0.5 / 9999).
- Difetto corretto: `infer_tour` usava tutte le righe del dataset (anche
  successive al fold); ora usa solo partite di date precedenti. Cambiano solo
  `hgb_with_odds_per_inferred_tour` e il segmento `tour_inferred`.
- Quote: medie dei bookmaker dello snapshot in `fixture.odds`; nessun timestamp
  di cattura, presumibilmente quote di chiusura, non verificabile offline. In
  serving il modello legge lo snapshot disponibile alla generazione della
  predizione: i modelli basati sul mercato sono probabilmente piu' informati nel
  benchmark che in produzione.
- Arricchimento ATP presente solo nei fold 2023Q3 (quota righe test 0.5018) e
  2024Q4 (0.4599); 0 dal 2025Q1.

## 5. Scostamento train/serve

Misurato dentro i fold (stesso modello `v4_like` riaddestrato per fold, due modi
di valorizzare le feature di test) e, a parte, sull'artefatto di produzione
(in-sample, solo differenze tra varianti). Numeri in `TEST_REPORT.md` e nel
`.md` del benchmark. Modello di produzione non toccato. Verificato che
l'emulazione del benchmark (`apply_serving_enrichment_defaults`) produce sull'artefatto
v4 la stessa probabilita' del percorso di serving reale (differenza 0.0).

## 6. Indizi

- (a) Calibrazione non applicata in inferenza — **VERIFICATO**. La probabilita'
  pubblicata nasce da `pipeline.predict_proba` (`predictor.py:582-583`) e viene
  salvata cosi' com'e' (`predictor.py:653`, `:661`); letta da DB in
  `services/predictions.py` (`_prediction_read`). L'artefatto v4 non contiene
  calibratori (ispezione: LogisticRegression, XGBClassifier,
  HistGradientBoostingClassifier in VotingClassifier soft). `apply_calibrator`
  e' usato solo in analisi offline (`ml/training/calibration.py:629`, `:731`,
  `services/slip_shape_trial.py:386`). Su main EV/PLAY usano la riduzione verso
  il mercato (`single_match_value.py`), non una calibrazione.
- (b) Nessuna astensione per giocatori senza storico — **VERIFICATO**, prima e
  dopo il punto 3. `predict_fixture` si astiene solo per chiavi/data mancanti
  (`predictor.py:522`, main `:418`) e quote mancanti v3/v4 (`predictor.py:544`,
  main `:439`); senza storico produce comunque una probabilita' (main `:321`
  aggiunge solo un warning). Dopo il punto 3 la predizione resta pubblicata ma
  `data_quality.status = "limited"` (test `test_no_history_is_limited_not_hidden`).

## 7. File di esempio

`git diff origin/main...HEAD`: solo nomi di variabili e valori numerici/di
policy in `.env.staging.example` e `backend/properties/config.env.example`;
nessun segreto. Gli unici hash nel diff sono gli sha256 del dataset e
dell'artefatto nel report del benchmark. Fuori dal diff, `.env.example:17`,
`:20-21`, `:39` contengono password di sviluppo banali preesistenti su main
(non introdotte dal branch).

## Rischi residui

- Breaker per processo: con piu' worker ognuno conta i propri fallimenti.
- `PREDICTION_DATA_QUALITY_HISTORY_ENABLED=true` non provato su PostgreSQL di
  produzione (latenza sconosciuta).
- Skew train/serve confermato ma non risolto: il serving passa 0 alle 13 colonne
  di arricchimento; correggerlo (`impute` o riaddestramento) cambia le
  probabilita' pubblicate e richiede una decisione esplicita.
- Provenienza/istante delle quote storiche non verificabile.
