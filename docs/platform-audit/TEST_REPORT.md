# Test Report — Tennis Oracle

Tutti i numeri sotto sono stati prodotti il 17/11/2026 (UTC) su questa macchina,
offline (nessuna chiamata a provider esterni: HTTP verso API-Tennis bloccato da
`backend/tests/conftest.py`, client testato con `requests` mockato).

## Suite completa

Comando (root del repo):
`OMP_NUM_THREADS=1 python3 -m pytest -q -p no:cacheprovider --no-cov -o addopts=""`

| commit | quando (UTC) | esito |
|---|---|---|
| `4bd7281` (`origin/main`, worktree separato) | 13:08-13:12 | **778 passed**, 0 failed, 246.16 s |
| `797e880` | 10:11-10:13 | **862 passed**, 0 failed, 129.35 s |
| `a25b162` | 13:16-13:19 | **872 passed**, 0 failed, 148.53 s |

Il commit di documentazione successivo non cambia codice; la suite e' stata
rieseguita anche li' (vedi il messaggio di chiusura nel resoconto della sessione).
Lo stato a `5515aec` (846 test raccolti) non e' stato eseguito per intero in
questa sessione: la prima esecuzione e' rimasta bloccata per contesa di CPU con
processi esterni ed e' stata interrotta. Il valore "842 passed" del log
dell'11/11 non e' stato riverificato.

La suite riscrive il file tracciato
`backend/data/reports/over_under_games_chained_experiment_results.json`:
ripristinarlo con `git checkout --` prima di ogni commit.

## Test aggiunti o estesi (moduli)

- `backend/tests/test_request_api_resilience.py`: retry (successo dopo retry,
  esaurimento, 429/5xx si', 4xx no, Retry-After con tetto, errore del provider e
  JSON non valido non ritentati, budget di tempo), breaker (chiuso -> aperto ->
  half-open -> chiuso, probe fallita riapre, 4xx non aprono, probe rilasciata su
  eccezione inattesa), metriche, concorrenza (singleton tra thread, una sola
  probe half-open, 16 thread con provider giu': breaker aperto una sola volta),
  nessuna chiave nei traceback/log/causa (anche URL-encoded e dopo retry).
- `backend/tests/test_next_fixtures_odds_status.py`: errore provider vs nessuna quota.
- `backend/tests/test_predictor_missing_features.py`: policy di riempimento
  (default = comportamento storico, uguaglianza esatta), `data_quality` in inferenza.
- `backend/tests/test_prediction_freshness_fields.py`,
  `backend/tests/test_prediction_data_quality_read.py`: campi additivi
  dell'endpoint `GET /api/next-fixtures/predictions`, storico opt-in uguale a
  quello ingerito dal predittore, colonne ATP non costruite in serving uguali a
  quelle mancanti all'artefatto v4.
- `backend/tests/test_match_winner_benchmark.py`: primitive (Elo, batching per
  giorno, metriche, bootstrap), run end-to-end su dati sintetici (nessun modello
  riceve `atp_score`/`atp_minutes`, addestramento solo su righe precedenti al
  fold, contendenti e segmenti richiesti), etichetta del circuito indipendente dal
  futuro, report committato coerente con il dataset (sha256) e con il `.md`.

## Benchmark walk-forward (offline)

Comando: `python -m backend.src.app.ml.benchmarks.match_winner_walk_forward`
(con `OMP_NUM_THREADS=2`), exit 0, 13:08:37-13:15:14 UTC; report generato alle
13:15:05 UTC. Output:
`backend/data/reports/benchmarks/match_winner_walk_forward_benchmark.json` e
`match_winner_walk_forward_benchmark.md` (tabelle complete, segmenti, calibrazione).

Dataset `backend/data/processed/tennis_winner_dataset_with_odds_v3.csv.gz`
(sha256 `752eebae…5ee3`): 338.564 righe (1990-02-05..2026-06-21), 99.983 con
`avg_player_1_odds` presente, 99.982 con quote valide (2021-10-07..2026-06-21),
target `target_player_1_win` (media 0.5112, nessun nullo). 8 fold trimestrali,
87.504 righe di test.

Riproducibilita': il codice di `5515aec` rilanciato riproduce il JSON committato
(8708 valori, unica differenza l'indentazione di una docstring dovuta a Python
3.13 vs 3.12).

| modello | n | log loss | Brier | ECE | accuratezza | delta log loss vs mercato [IC95] |
|---|---|---|---|---|---|---|
| `market_no_vig` | 87504 | 0.55906 | 0.18969 | 0.0181 | 0.7075 | riferimento |
| `market_logit_recalibrated` | 87504 | 0.55720 | 0.18928 | 0.0084 | 0.7077 | -0.00186 [-0.00222, -0.00151] |
| `elo_overall_k32` | 87504 | 0.60284 | 0.20817 | 0.0200 | 0.6700 | +0.04378 [+0.04206, +0.04547] |
| `elo_surface_k32` | 87504 | 0.62553 | 0.21823 | 0.0152 | 0.6439 | +0.06647 [+0.06431, +0.06855] |
| `elo_overall_dynamic` (K dinamico + decadimento, `dyn_k250_tau365`) | 87504 | 0.59151 | 0.20351 | 0.0058 | 0.6790 | +0.03244 [+0.03074, +0.03412] |
| `lr_no_odds` | 87504 | 0.58357 | 0.20014 | 0.0041 | 0.6858 | +0.02451 [+0.02301, +0.02613] |
| `hgb_no_odds` | 87504 | 0.58403 | 0.20026 | 0.0053 | 0.6861 | +0.02496 [+0.02344, +0.02651] |
| `lr_with_odds` | 87504 | 0.55771 | 0.18960 | 0.0082 | 0.7066 | -0.00135 [-0.00183, -0.00082] |
| `hgb_with_odds` | 87504 | 0.55820 | 0.18984 | 0.0053 | 0.7057 | -0.00086 [-0.00147, -0.00026] |
| `xgb_with_odds` | 87504 | 0.55704 | 0.18943 | 0.0056 | 0.7071 | -0.00202 [-0.00248, -0.00153] |
| `v4_like__true_features` | 87504 | 0.55677 | 0.18927 | 0.0050 | 0.7068 | -0.00230 [-0.00275, -0.00184] |
| `v4_like__serving_enrichment_zeros_and_rank_fallback` | 87504 | 0.56308 | 0.19192 | 0.0371 | 0.7010 | +0.00402 [+0.00336, +0.00474] |

Avvertenza: le quote del dataset non hanno timestamp (presumibilmente di
chiusura); in produzione il modello vede quote precedenti. Il vantaggio dei
modelli con quote sul mercato e' piccolo (millesimi di log loss) e potrebbe non
trasferirsi.

## Scostamento train/serve

Stesso modello `v4_like` (algoritmi e 38 feature dell'artefatto v4) riaddestrato
in ogni fold; in test le 13 colonne di arricchimento ATP sono valorizzate come
nel dataset (riferimento) oppure con 0 come fa oggi il serving. Delta =
candidato − riferimento, IC 95% bootstrap appaiato (1000 ricampionamenti), n = 87.504.

| confronto | delta log loss [IC95] | delta Brier [IC95] | accuratezza (delta [IC95]) | pronostici invertiti |
|---|---|---|---|---|
| serving con 0 vs feature reali | +0.00624 [+0.00551, +0.00696] | +0.00263 [+0.00233, +0.00293] | 0.7013 vs 0.7068 (-0.00558 [-0.00743, -0.00369]) | 7.97% |
| serving con 0 + ranking assente vs feature reali | +0.00632 [+0.00558, +0.00704] | +0.00266 [+0.00234, +0.00297] | 0.7010 vs 0.7068 (-0.00582 [-0.00767, -0.00390]) | 8.06% |
| colonne dichiarate mancanti vs feature reali | -0.00011 [-0.00023, +0.00001] | -0.00005 [-0.00010, -0.00000] | 0.7072 vs 0.7068 (+0.00038 [+0.00002, +0.00073]) | 0.27% |

Peggioramento con 0 in tutti gli 8 fold (delta log loss per fold da +0.00283
a +0.01212; massimo nel 2023Q3, quota di righe di test arricchite 0.5018; 2024Q4
+0.00577 con quota 0.4599). ECE da 0.0050 a 0.0371. Nei fold dal 2025Q1 le "feature
reali" sono valori mancanti (quota arricchita 0), quindi li' il confronto misura
"mancante" contro "0".

Artefatto di produzione `backend/data/models/v4/voting_ensemble.pkl` (sha256
`5918cf84…49ad`), IN-SAMPLE (addestrato su questo dataset: solo le differenze
sono informative), 66.633 righe dal 2025-01-01: valori del dataset log loss
0.55268 / Brier 0.18790 / accuratezza 0.7084 / ECE 0.0060; riempimento con 0
0.55527 / 0.18888 / 0.7071 / 0.0252 (delta log loss +0.00259 [+0.00216, +0.00303],
pronostici invertiti 3.37%, probabilita' media 0.4925 contro 0.5102 e target
medio 0.5121).

## Altre verifiche (comandi eseguiti il 17/11)

- Audit leakage indipendente sul dataset (script locale nello scratchpad):
  H2H, forma ultimi 5, partite ultimi 14 giorni, giorni dall'ultima partita
  ricalcolati solo da date precedenti: 0 discrepanze, salvo le righe senza storico
  dove il dataset usa i sentinel 0.5 / 9999.
- `grep -rln "atp_minutes\|atp_score" backend/src`: solo nelle liste di
  esclusione (`train_baseline.py:146-147`, `POST_MATCH_COLUMNS` del benchmark),
  nel modulo che costruisce l'arricchimento (`atp_singles_enrichment.py`) e in
  una docstring (`score_parser.py:10`); nessuna lista di feature li contiene
  (verificato anche per v1-v4 con `allowed_feature_columns`).
- Emulazione serving del benchmark = percorso di serving reale sull'artefatto v4
  (differenza di probabilita' 0.0 su una partita sintetica).
- Ispezione artefatto v4: nessun calibratore (VotingClassifier soft di
  LogisticRegression, XGBClassifier, HistGradientBoostingClassifier).
