# Piano beta gratuita → monetizzazione

Criteri oggettivi per decidere **quando** passare da "bot in beta gratuita, base utenti piccola" a
"promozione attiva degli abbonamenti a pagamento". Nasce dalla domanda: *conviene pubblicizzare
ora?* — risposta: sì per farsi conoscere in beta gratuita, no per spingere sui pagamenti finché
non sono soddisfatte le soglie qui sotto.

Non è una policy tecnica del codice (nessun gate automatico blocca `/abbonati`): è una checklist
operativa per una decisione umana, da rivedere ogni settimana insieme al **Report settimanale
beta** già generato dal sistema.

---

## Stato di partenza (misurato, non stimato)

| Dato | Valore | Fonte |
|------|--------|-------|
| ROI backtest v4 (holdout singolo) | -2.49% | `data/reports/model_comparison.json` (v4, voting_ensemble, value_bet_overall) |
| ROI backtest v4 (walk-forward completo, 10 fold) | -3.45% / -4.55% | `data/reports/v4_walk_forward_results.json`, `v4_serve_stats_experiment_results.json` |
| ROI backtest v1/v2/v3 | da -16.8% a -2.4% | `data/reports/model_comparison.json` |
| Tip pubblicati live (campione osservato) | ~92 in 19 giorni (22 lug–10 ago 2026) | `check_clv_ml_readiness.py` (report `clv_ml_readiness_check.json`) |
| Copertura CLV live | 9.8% (9/92), 0/48 in una settimana intera | idem, vedi anche `SCHEDULING.md#closing-odds-job-futuro` |
| Infrastruttura tecnica (bot, abbonamenti, monitoring) | Pronta | `GUIDA_UTENTE.md`, `MONITORING.md` |

**Sintesi**: nessuna versione del modello ha mai chiuso un backtest con ROI ≥ 0. Il campione live
è troppo piccolo per sapere se la realtà operativa conferma o smentisce il backtest. La parte
prodotto/infrastruttura è invece già matura.

---

## Fase 1 — Beta gratuita ampia (da fare subito)

Obiettivo: più utenti, più dati live, più feedback — **senza** spingere sugli abbonamenti a
pagamento.

1. Amplia gli inviti nella whitelist (**Utenti beta Telegram**), oltre alla cerchia attuale.
2. Comunicazione sempre esplicita: *"prodotto in fase beta, storico ancora limitato, nessuna
   garanzia di profitto"* — coerente con il disclaimer già presente in `GUIDA_UTENTE.md`, ma da
   ripetere in ogni canale esterno (social, gruppi, landing page) usato per farsi conoscere.
3. Tieni la prova/piano gratuito come porta d'ingresso principale; non forzare `/abbonati` nei
   messaggi broadcast di questa fase.
4. Massimizza la raccolta di `/feedback` (già pronto): è il segnale qualitativo più economico che
   hai a disposizione mentre il campione quantitativo cresce.
5. In parallelo, **attiva** il job di polling CLV dedicato pre-kickoff (`run_closing_odds_capture`,
   vedi `SCHEDULING.md#closing-odds-job-dedicato-pre-kickoff`): è già implementato ma disabilitato
   di default (`CLOSING_ODDS_JOB_ENABLED=false`); serve `CLOSING_ODDS_JOB_ENABLED=true` **+** un
   cron/Task Scheduler che lo richiami ogni 1-5 minuti — senza CLV affidabile non potrai mai
   distinguere "abbiamo scelto bene il timing" da "abbiamo avuto fortuna sull'esito".

---

## Soglie minime prima di spingere sulla monetizzazione

Tutte e quattro devono essere vere **contemporaneamente**. Sono soglie deliberatamente prudenti:
un campione piccolo che sembra positivo per caso costa più caro (in reputazione) di qualche
settimana di attesa in più.

| # | Soglia | Perché questo numero | Come verificarlo |
|---|--------|----------------------|-------------------|
| 1 | **≥ 300 tip chiuse** (won/lost, non void) cumulate dall'inizio della raccolta seria | Stesso ordine di grandezza della soglia già usata per il CLV (200), alzata perché il ROI ha varianza più alta del semplice tasso di copertura | `published_live_stats.compute_published_live_stats` → campo `closed` |
| 2 | **≥ 8 settimane consecutive** di osservazione | Copre più tornei/superfici/periodi, riduce il rischio "mese fortunato" | Conteggio `WeeklyBetaReport` generati consecutivamente |
| 3 | **ROI cumulativo live ≥ -2%** (idealmente ≥ 0%), calcolato sulle tip chiuse | Non preteendo un ROI positivo garantito, ma va escluso un trend sistematicamente in perdita marcata come nel backtest | Dashboard **Statistiche live** / `compute_published_live_stats` → `roi_pct` |
| 4 | **Nessun mese con drawdown "critico"** (definisci una soglia assoluta di stake, es. -30% dello stake cumulato) nelle ultime 8 settimane | Un solo mese pessimo non deve essere mascherato da una media cumulata ancora accettabile | `max_drawdown` in Statistiche live / weekly report |

Se anche **una sola** soglia non è soddisfatta al momento della verifica: resta in beta gratuita,
rivedi tra 2-4 settimane.

---

## KPI da guardare ogni settimana (già calcolati automaticamente)

Il **Report settimanale beta** (`WeeklyBetaReport`, generabile manualmente o dal job del lunedì)
include già tutto quello che serve, senza bisogno di nuovi script:

| Sezione payload | Campi chiave | A cosa serve qui |
|------------------|--------------|-------------------|
| `users` | `total_users`, `new_users`, `active_users`, `retention_pct` | Il bot sta crescendo? Chi arriva, resta? |
| `live_tips` | `roi_pct`, chiusi/aperti/void | Traccia soglia #3 settimana per settimana |
| `feedback` | conteggi per categoria/voto | Segnali qualitativi anticipatori (spesso arrivano prima dei numeri) |
| `pipeline` | errori, durata | Se la pipeline è instabile, non ha senso scalare utenti finché non è risolto |
| `notifications` | consegne fallite | Un bot che promette notifiche e non le manda brucia fiducia in fretta |

Aggiungi a mano, ogni settimana, solo il conteggio cumulato delle tip chiuse (soglia #1) e delle
settimane consecutive osservate (soglia #2): non serve automatizzarlo finché il volume resta
gestibile manualmente.

---

## Criterio di decisione (go / no-go)

```
SE (tip_chiuse_cumulate >= 300)
   E (settimane_consecutive_osservate >= 8)
   E (roi_cumulativo_live >= -2%)
   E (nessun mese con drawdown oltre soglia critica)
ALLORA
   -> valuta l'avvio di una promozione attiva degli abbonamenti a pagamento
   -> mantieni comunque il disclaimer di rischio, anche a monetizzazione attiva
ALTRIMENTI
   -> resta in beta gratuita
   -> rivedi le soglie tra 2-4 settimane
   -> nel frattempo: job CLV dedicato, eventuale restrizione a segmenti più solidi
      (vedi nota sotto)
```

## Leva aggiuntiva: restringere invece di aspettare e basta

Dalle analisi di segmentazione ROI già fatte (`v4_segment_roi_by_level.json`), i segmenti
"Tour" (A/M/G) e Challenger risultano sistematicamente meno negativi degli ITF/Futures, pur
restando negativi nel backtest complessivo. Se il campione live confermasse la stessa gerarchia,
un'opzione intermedia è **promuovere il bot per un sotto-insieme di tornei** (es. solo Tour +
Challenger) invece che per l'intero circuito: riduce il volume di tip ma può alzare la qualità
media prima ancora di raggiungere le soglie sopra sull'intero portafoglio.

---

## Cosa NON fare nel frattempo

- Non promettere ROI o percentuali di vincita in comunicazione esterna (social, landing page):
  il backtest storico non lo supporta ancora.
- Non disattivare il disclaimer beta solo perché il numero di utenti cresce: la crescita utenti
  e la validazione del modello sono due assi indipendenti.
- Non ignorare un mese negativo isolato "mediandolo" nel cumulato se supera la soglia di
  drawdown critico: è proprio il caso che la soglia #4 vuole intercettare.

---

## Prossima revisione

Rivedi questo piano quando:
- il job di polling CLV dedicato (`run_closing_odds_capture`, implementato ma da **abilitare**
  con `CLOSING_ODDS_JOB_ENABLED=true` + cron frequente) ha accumulato qualche settimana di dati
  (cambia la soglia #3, potendo usare CLV oltre al ROI grezzo come segnale di qualità del timing);
- oppure ogni 4 settimane, insieme al Report settimanale beta, finché le 4 soglie non sono tutte
  soddisfatte.



