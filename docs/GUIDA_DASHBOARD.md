# Guida operativa dashboard — Tennis Oracle

Manuale **pagina per pagina** per l’amministratore che usa la UI ogni giorno, senza entrare nel codice.

Per avvio, login, bot Telegram e flusso quotidiano generale vedi [GUIDA_UTENTE.md](GUIDA_UTENTE.md).  
Per architettura, API e ML vedi [README.md](../README.md).

---

## Come leggere questa guida

Il menu laterale replica l’ordine delle sezioni qui sotto. Due famiglie di dati restano **separate**:

| Famiglia | Cosa misura | Pagine tipiche |
|----------|-------------|----------------|
| **LIVE** | Tip salvati nel registro immutabile (`published_prediction`) | Dashboard live, Storico pubblicazioni, Statistiche live |
| **Operativo / backtest** | Previsioni salvate, schedine simulate, validazione ML offline | Partite, Consiglio schedina, Statistiche previsioni, Walk-forward, … |

Non confondere **previsioni operative** (tutte le partite con modello salvato) con **pubblicazioni live** (solo tip PLAY del modello pubblico, se abilitato).

### Metriche condivise (live e analisi ROI)

Definizioni allineate al registro live e alle pagine di analisi:

| Metrica | Significato |
|---------|-------------|
| **Aperta / open** | Partita non ancora liquidata (stake ancora “in gioco”). |
| **Void** | Partita annullata o non scommettibile: stake restituito, **esclusa** da hit rate e ROI. |
| **Chiusa / closed** | Vinta o persa: lo stake è stato messo a rischio. |
| **Hit rate** | Vinte ÷ (vinte + perse). Void e aperte **non** entrano. |
| **Stake totale** | Somma degli stake pubblicati (include aperte e void). |
| **Stake settled** | Somma stake solo su vinte+perse: **denominatore** di ROI/yield. |
| **Profitto** | Somma P/L realizzato (vinta: stake×(quota−1); persa: −stake; void/aperta: 0). |
| **ROI % / Yield %** | Profitto ÷ stake settled × 100 (identici per convenzione prodotto). |
| **Max drawdown** | Massimo calo peak→trough sulla curva cumulata dei tip **chiusi** in ordine cronologico. |
| **Serie +/-** | Serie massima di vittorie / sconfitte consecutive (void/aperte saltate). |
| **IC 95%** | Intervallo di confidenza (Wilson sul hit rate; bootstrap sul ROI dove indicato). |
| **PLAY / BORDERLINE / NO BET** | Confronto quota di mercato vs **quota void** (1 ÷ probabilità modello) ± **margine di sicurezza** (default 2%). |

---

# Principale

## Dashboard live — `/live-beta-dashboard`

### A cosa serve

Vista unica **operativa LIVE** sui tre mercati attivi: Vincitore partita, Vincitore 1° set e Over/Under Games. Separa sempre le prestazioni di tutti i pronostici pubblicati da quelle dei soli **PLAY ufficiali**, oltre a mostrare stato pipeline, completezza dati, stato essenziale del bot ed errori recenti.

### Quando aprirla

- Ogni mattina, dopo **Aggiorna tutto**, per un colpo d’occhio su pipeline e tip del giorno.
- Quando sospetti che le pubblicazioni automatiche non partano o il registro sia vuoto.
- Per monitorare hit rate e risultati di un singolo mercato senza mescolare popolazioni diverse.
- Prima di una riunione settimanale, insieme al report settimanale beta.

### Cosa NON fa / con cosa non confonderla

- **Non** include metriche di training, walk-forward o backtest.
- **Non** sostituisce **Partite** (previsioni su tutto il calendario) né **Statistiche live** (analisi più profonda delle distribuzioni).
- **Non** aggrega ROI o hit rate di mercati diversi: si consulta sempre un mercato alla volta.
- I nomi tecnici degli artefatti ML restano nelle pagine amministrative dedicate, non sono controlli operativi di questa pagina.

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Mercato | Vincitore partita / Vincitore 1° set / Over/Under Games | Nessuna vista “Tutti”: evita KPI misti |
| Data pubblicazione da / a | Periodo su data **pubblicazione** | Default ~ultimi 90 giorni; non è la data dell’evento |
| Torneo | Filtro testuale (Invio o blur) | Es. “Roland Garros”; match parziale |
| Superficie | Hard, Clay, Grass, Carpet | Utile per confrontare segmenti |
| Fascia quota | &lt;1.50, 1.50–2.00, 2.00–3.00, ≥3.00, senza quota | Per capire se il ROI live viene da favoriti o outsider |
| Solo revisione più recente | Sempre attiva: i KPI usano l’ultima revisione di ogni pubblicazione | Non è un interruttore in pagina |
| Includi storico | Include versioni Match Winner archiviate | OFF nell’uso quotidiano; visibile solo sul mercato Vincitore partita; serve per audit |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Stato registro / Validazione live | Perché il registro è vuoto o attivo | Se `publication_disabled` o modello non configurato, i KPI resteranno a zero per design |
| Pipeline LIVE | Ultimo run globale, fase, import calendario | Link al report aggiornamento; verifica “import oggi = Sì” |
| Tutti i pronostici | Totali, aperti, risolti, void e hit rate del mercato | Misura il segnale predittivo, non la redditività delle giocate consigliate |
| PLAY ufficiali | Conteggi e hit rate dei soli tip classificati PLAY | È la popolazione usata per i KPI finanziari |
| Profitto / ROI / Max drawdown | Performance dei PLAY con quota reale | Valori in **unità di stake**, non euro; il Primo set mostra `—` |
| CLV medio / CLV copertura | Qualità della quota presa rispetto al closing dello stesso mercato | CLV medio > 0 = prezzo migliore; assenza di snapshot market-aware → `—` |
| Pubblicazioni recenti | Dettaglio singoli tip, ordinati dal più recente | La pagina dichiara esplicitamente il limite delle righe mostrate |
| Completezza dati | % tip con quota, data, match, snapshot quote | Coverage closing bassa → analisi CLV limitata |
| Stato bot | Segnale sintetico di utilizzo/fallimenti | Il dettaglio resta nella pagina **Bot Telegram** |
| Errori recenti | Pipeline o bot | Investiga subito se compaiono messaggi ripetuti |

### CLV nella Dashboard live

- **Quota pubblicazione**: quota associata al tip al momento publish per lo stesso mercato e, se presente, la stessa linea.  
- **Closing odds**: quota di chiusura rilevata su snapshot `closing` dello stesso mercato; non vengono riutilizzate quote Match Winner per il Primo set.  
- **CLV %**: `((quota_pubblicazione / closing_odds) - 1) * 100`.  
- **Interpretazione rapida**:
  - CLV positivo: hai preso un prezzo migliore del closing;
  - CLV negativo: hai preso un prezzo peggiore;
  - CLV non disponibile: mancano closing odds affidabili per quel tip.

Per capire se il segnale è robusto, guarda sempre **CLV copertura** insieme a **CLV medio**.

### Esempio pratico

1. Esegui **Aggiorna tutto** dalla sidebar.  
2. Apri la dashboard e seleziona **Vincitore partita**.  
3. Controlla separatamente hit rate di tutti i pronostici e ROI dei PLAY ufficiali.  
4. Passa a **Over/Under Games** senza confrontare direttamente campioni o quote con il mercato precedente.  
5. Sul **Vincitore 1° set** leggi hit rate e, quando c’è quota `Home/Away (1st Set)`, anche ROI/CLV dei PLAY ufficiali.

### Segnali da tenere d’occhio

- Banner registro vuoto con messaggio esplicativo (pubblicazione disabilitata, nessun PLAY qualificato, errori).  
- `closing_odds_status: missing` → non usare questi tip per studi di chiusura linea.  
- Storico Match Winner necessario per spiegare i KPI correnti → abilita temporaneamente “Includi storico”.  
- Errori recenti in `global_update` dopo ogni run.

### Limiti noti

- La salute della pubblicazione Match Winner dipende da `LIVE_PUBLICATION_ENABLED` e dal modello attivo nel registro ML-07.
- Il Primo set usa le quote `Home/Away (1st Set)` per void/edge/ROI/CLV; i tip storici senza quota restano solo nell’hit rate.
- Il closing Over/Under resta best-effort finché non esiste una cattura pre-kickoff frequente per quel mercato.
- Quote e contesto torneo possono essere incompleti su eventi minori.

---

## Partite — `/predictions`

### A cosa serve

Calendario partite con **previsioni salvate** per ogni versione/modello disponibile, quota void e classificazione valore (PLAY / BORDERLINE / NO BET). Supporta la scelta quotidiana delle giocate e il controllo retrospettivo sulle giocate concluse.

### Quando aprirla

- Mattina: tab **Da giocare** per pronostici del giorno.  
- Dopo i match: tab **Giocate** + **Importa disputate** o **Aggiorna tutto**.  
- Per cercare un giocatore o confrontare logistic vs random forest sulla stessa partita.

### Cosa NON fa / con cosa non confonderla

- **Non** è lo storico **pubblicazioni live** (ledger immutabile).  
- **Non** genera schedine multi-leg (vedi **Consiglio schedina**).  
- Stato **Da generare** = nessuna previsione salvata, **non** necessariamente errore di aggiornamento.  
- Le statistiche aggregate storiche sono in **Statistiche previsioni**.

Dettaglio su margine, void e stati partita: [GUIDA_UTENTE.md — Margine di sicurezza](GUIDA_UTENTE.md#margine-di-sicurezza-e-stati-valore).

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Tab versione (v1/v2/v3) | Quale feature set / uso quote | Default v3 in UI; v1/v2 ignorano quote in predizione |
| Margine sicurezza (%) | Soglia sopra void per PLAY | Default **2**; a **0** solo BORDERLINE→PLAY |
| Tab Da giocare / Giocate / Tutte | Stato calendario | Giocate = ultimi 30 giorni concluse |
| Prese / Perse (solo Giocate) | Filtra per esito previsione | Utile per error analysis |
| Cerca giocatore | Filtro nome | Invio o pulsante Cerca |
| Importa disputate + giorni indietro | Import risultati senza run completa | 1–3 giorni routine; 7+ dopo weekend lungo |
| Paginazione | 50 partite per pagina | — |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Predetto | Vincitore stimato dal modello | Confronta colonne se hai 2 modelli affiancati |
| Conf. | Confidenza modello (0–100%) | Non è probabilità grezza; complemento alla probabilità |
| Void | Quota break-even = 1 ÷ P(vittoria) | Sotto questa quota il modello dice “no value” |
| Valore | PLAY / BORDERLINE / NO BET | Ricalcolato live al variare del margine |
| Stato | Lifecycle partita | Rinviata ≠ annullata; **Da generare** = senza prediction |
| Pallino verde/rosso (Giocate) | Previsione corretta/errata | Solo se esito disponibile |
| Stato import (pannello) | Copertura calendario e ultimo import | Se calendario incompleto → Aggiorna tutto |

### Esempio pratico

1. Tab **v3**, margine **2%**, filtro **Da giocare**.  
2. Ordina mentalmente per badge **PLAY** (contatore in header).  
3. Per un match interessante, confronta Logistic e Random Forest.  
4. Sera: **Giocate** → verifica pallini; se mancano esiti, **Importa disputate** 1 giorno.

### Segnali da tenere d’occhio

- Molte righe **NO BET** con confidenza alta → mercato efficiente o margine alto.  
- **Da generare** su partite imminenti → run globale mancante o dati/quote assenti (v3).  
- Contatori PLAY/BORDERLINE/NO BET vs pool schedine (pagina schedine).

### Limiti noti

- v3 richiede quote; partite senza odds restano senza valore.  
- Giocate mostra anche partite **senza** previsione (celle vuote).  
- Value ricalcolato lato browser dal margine: non richiede nuova chiamata API.

---

## Consiglio schedina — `/betting-slips`

### A cosa serve

Propone le schedine multi-leg e le scalate progressive in quattro sotto-sezioni confrontabili. **Generiche** conserva i profili storici (fino a 10 schedine e 3 scalate); **Solo PLAY**, **Mercati forti** e **Selettive** sono corsie sperimentali indipendenti. Le scalate reinvestono il ritorno di ogni step nello step successivo (ordine di orario).

### Quando aprirla

- Dopo l’aggiornamento globale, per scegliere profilo rischio (sicura vs value).  
- Per copiare testo schedina (pulsante **Copia schedina**) verso app o bot.  
- Per scaricare le immagini PNG (**Scarica immagini** = tutte; **Scarica immagine** = singola), uguali a quelle del bot.  
- Per rivedere performance storica per profilo (Play sicura, bilanciata, …).

### Cosa NON fa / con cosa non confonderla

- **Non** pubblica automaticamente nel registro live (salvo pipeline dedicata sui PLAY singoli).  
- Le tre corsie sperimentali **non** vengono inviate dai comandi o dai recap Telegram ufficiali finché non vengono promosse.
- **Non** sostituisce analisi ROI per segmento.  
- **Media quote bookmakers** = media mercato sul pick, non quota singolo bookmaker.  
- **Void** in colonna = quota break-even, non partita annullata (pick **Annullato** = void settlement).

Profili e regole settlement: [GUIDA_UTENTE.md — Consiglio schedine](GUIDA_UTENTE.md#consiglio-schedine-difficoltà).

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Tab versione / modello | Una lista schedine alla volta | Confronta modelli cambiando tab |
| Sotto-tab strategia | Generiche / Solo PLAY / Mercati forti / Selettive | Cambia famiglia senza eliminare i profili esistenti |
| Calendario (storico / prossime) | Giorno da analizzare | Rigenera solo **oggi/futuro** |
| Margine sicurezza | Ricalifica PLAY/BORDERLINE/NO BET | Coerente con pagina Partite |
| Simula puntata (€) | Ricalcola vincita/profitto | Default 10 €; preset 1–50 |
| Rigenera schedine | Ricrea fino a 10 profili sul pool del giorno (Doppia + Play / Border / Miste) | Disabilitato su giorni passati |
| Scarica immagini | ZIP PNG di tutte le schedine del giorno selezionato | Stesso layout del bot Telegram |
| Scarica immagine (per schedina) | PNG della singola schedina | Accanto a **Copia schedina** |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Label profilo | Es. Play · Doppia, Play sicura, Mista value | 10 varianti documentate in GUIDA_UTENTE |
| Media quote / Void / Edge / ROI | Valore singolo pick | Edge % = distanza da void; ROI atteso da quota vs probabilità |
| Valore | PLAY / BORDERLINE / NO BET | Rispetta margine pagina |
| Quota combinata / effettiva | Prodotto quote pick attive | Con pick annullate → quota effettiva ricalcolata |
| Stato schedina | Presa / Persa / In corso / Annullata | Una pick persa → schedina persa |
| Pool PLAY disponibile | Candidati giornata | Se basso, warning e schedine mancanti |
| Statistiche giorno / complessive | Win rate schedine, hit pick, profitto teorico | Pending esclusi dalle % |
| Confronto strategie | ROI standard e ROI giornaliero normalizzato | Il normalizzato assegna la stessa puntata totale a ogni famiglia/giorno |

### Sotto-tab sperimentali

Le corsie sperimentali vengono abilitate dal modello pubblico Match Winner `v4 / voting_ensemble`; questa etichetta non descrive l'intero pool. Le gambe Primo set usano `first_set_winner_v2 / logistic_regression`, quelle Over/Under `over_under_games_v1 / random_forest`. Tutte passano nello stesso flusso delle generiche: persistenza nel database, aggiornamento esiti, gestione void, storico e statistiche. Non modificano né ricostruiscono le schedine generiche già salvate.

- **Solo PLAY** — solo decisioni PLAY, eventi distinti; schedina da 3 pick e scalata da 3 step.
- **Mercati forti** (`strong_markets_v1`) — solo PLAY del mercato vincitore 1° set, su eventi distinti; 3 pick/step.
- **Selettive** (`selective_v1`) — versione più corta e prudente del mercato forte: schedina da 2 pick con quota combinata massima 3,20; scalata da 3 step con massimo 4,00.

La classifica mostra sia il ROI per singola uscita sia il **ROI giornaliero normalizzato**. Quest'ultimo è il confronto principale: simula una sola unità di budget per famiglia al giorno, divisa tra le uscite chiuse, evitando che Generiche pesi di più solo perché produce più profili. Una giornata entra nel confronto normalizzato solo quando la famiglia non ha più schedine in corso.

### Esempio pratico

1. Seleziona **oggi**, modello **logistic_regression**, v3.  
2. Leggi pool PLAY: se basso, aspettati meno schedine (la Doppia richiede almeno 2 PLAY).  
3. Confronta profilo **Play · Doppia** vs **Play sicura** vs **Mista bilanciata**.  
4. Apri **Solo PLAY**, **Mercati forti** e **Selettive** e confronta il ROI giornaliero normalizzato a parità di tipo (Schedine o Scalate).
5. Copia schedina scelta e monitora esiti (pallini verde/rosso/grigio).

### Segnali da tenere d’occhio

- Warning in pagina (pool insufficiente, pochi BORDERLINE).  
- Molte pick **Annullate** → quota effettiva molto sotto l’originale.  
- **Esito mancante** su giorni passati → import risultati incompleto.

### Limiti noti

- Profitto/ROI schedine = **simulazione** storica, non registro live.  
- Le giornate chiuse restano append-only; le nuove famiglie compaiono solo nelle giornate ancora generabili.
- Una pick persa invalida l’intera schedina.  
- In generazione/rigenerazione il pool esclude partite già **annullate / rinviate / abbandonate / esito mancante / in corso** (status noto al momento dell’update).

---

# LIVE

Il modello pubblico attivo (bot + pubblicazione automatica) è gestito via **API** `/api/public-model-registry` (ML-07), non da una pagina UI: in LIVE si sceglie il **mercato**, non il modello.

## Storico pubblicazioni — `/published-predictions`

### A cosa serve

Registro **immutabile** di ogni tip pubblicato: probabilità, quote, edge, hash contenuto, versione e fonte. Audit trail per validazione live e conformità (“cosa abbiamo detto prima dell’inizio match?”). Un mercato alla volta (Match / 1° set / O/U).

### Quando aprirla

- Verificare cosa è stato pubblicato in una data.  
- Tracciare **correzioni** (nuova versione stesso `publication_id`).  
- Cercare per `event_key` o fonte (`global_update`, `telegram`, …).

### Cosa NON fa / con cosa non confonderla

- **Non** mostra previsioni mai pubblicate (vedi **Partite**).  
- Dopo inizio partita la riga è **congelata**; modifiche = nuova versione, non edit in place.  
- KPI aggregati → **Statistiche live** o **Dashboard beta live**.  
- **Non** mescola mercati: usa i tab Mercato.

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Tab Mercato | Match / 1° set / Over-Under | Default **Vincitore partita**; KPI non misti |
| Da / A | Intervallo date pubblicazione | Default ultimi 30 giorni |
| Event key | ID tecnico partita | Da log o tabella Partite |
| Fonte | Filtro `publication_source` | Es. `global_update` |
| Solo versione corrente | Nasconde versioni supersedute | ON per lista “ufficiale” |
| Paginazione | 50 righe | Pulsante **Versioni** per catena |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| UTC | Timestamp pubblicazione | Orario UTC in tabella |
| Mercato | Match / 1° set / O/U | Badge allineato al tab selezionato |
| P | Probabilità modello al publish | Confronta tra versioni se corrette |
| Quota / Void / Edge | Snapshot al momento publish | Edge in % punti |
| Stake | `unit_stake` registrato | Unità base profitto/ROI live |
| Ver | `content_version` | Incrementa a ogni re-pubblicazione |
| Stato | congelata / superseduta | `match_started` → non editabile |
| Hash | Impronta contenuto | Audit anti-manomissione |

### Esempio pratico

1. Filtra ultima settimana, solo versione corrente.  
2. Trova partita sospetta → **Versioni** → confronta quota/edge tra v1 e v2.  
3. Se solo v2 è latest, KPI live con “solo versione recente” usano quella.

### Segnali da tenere d’occhio

- Molte righe **supersedute** → correzioni frequenti pre-match (verifica processo).  
- Edge negativo in ledger → non dovrebbe accadere su publish automatico PLAY.  
- Hash diverso a parità di selezione → cambiato qualcosa (quota, prob, stake).

### Limiti noti

- Lista vuota se pubblicazione automatica disabilitata.  
- Non mostra esito/post-match (esito in dashboard/statistiche live).

---

## Statistiche live — `/published-live-stats`

### A cosa serve

KPI e **distribuzioni** (per modello, quota, edge, superficie, mese) calcolati **solo** dal registro pubblicazioni, **un mercato alla volta**. È l’analisi performance “ufficiale” del tipbook live.

### Quando aprirla

- Review mensile performance tip pubblicati.  
- Capire se il ROI viene da una fascia quota o modello specifico.  
- Monitorare drawdown e streak nel tempo.

### Cosa NON fa / con cosa non confonderla

- **Non** usa previsioni operative né schedine (vedi **Statistiche previsioni** / **Statistiche schedine**).  
- **Non** è backtest ML (**Walk-forward**, **Fasce probabilità** con sorgente backtest).  
- Stesse regole void/hit rate/ROI della dashboard live; qui più breakdown tabellari.

Regole settlement: [GUIDA_UTENTE.md — Statistiche live](GUIDA_UTENTE.md#statistiche-live-registro-pubblicazioni).

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Tab Mercato | Match / 1° set / Over-Under | Default **Vincitore partita**; un mercato alla volta |
| Da / A | Periodo pubblicazione | Default ~90 giorni |
| Solo versione più recente | Esclude tip corretti/superseduti | **ON** per KPI ufficiali |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Cards riepilogo | Totali, chiusi, void, hit rate, ROI, drawdown | Void ≠ perdite; solo mercato selezionato |
| Cards CLV | Copertura, CLV medio, CLV mediano, % CLV positivo | Leggi il CLV insieme al campione disponibile |
| Per modello | KPI per versione/nome modello | Breakdown interno (non scegli il modello da UI) |
| Per quota | Fascia odds del tip | ROI alto su ≥3.00 spesso campione piccolo |
| Per edge | Fascia edge al publish | Verifica se PLAY alti edge performano |
| Per superficie / periodo | Segmentazione | Incrocia con **ROI per segmento** live |
| CLV nelle distribuzioni | Colonne “CLV copertura” e “CLV medio” per ogni bucket | Utile per capire dove il prezzo viene preso meglio/peggio |

### CLV nelle Statistiche live

- **Quota di pubblicazione**: quota al publish del tip (vedi definizione sopra).
- **Closing odds**: quota di chiusura dello stesso mercato.
- **Probabilità senza margine (no-vig)**: probabilità ripulita dall’overround bookmaker.  
  Formula usata: `p_no_vig = (1/odds_sel) / ((1/odds_sel) + (1/odds_opposta))`.
- **CLV %**: `((quota_pubblicazione / closing_odds) - 1) * 100`.
- **CLV positivo %**: percentuale tip con CLV > 0 tra quelli con CLV disponibile.

Uso pratico:
1. controlla **CLV copertura** (se troppo bassa, non trarre conclusioni forti);
2. poi confronta **CLV medio/mediano** per modello, superficie, quota ed edge;
3. infine incrocia con ROI/hit rate per distinguere varianza risultati da qualità del prezzo.

### Esempio pratico

1. Periodo ultimo trimestre, solo versione recente.  
2. Guarda **Per edge**: hit rate vs ROI per fascia.  
3. Se hit rate 55% ma ROI negativo su favoriti → quote medie troppo basse.  
4. Confronta **Max drawdown** con profitto totale (rischio vs rendimento).

### Segnali da tenere d’occhio

- Campione **chiusi** basso → ROI instabile.  
- Divergenza hit rate vs ROI → effetto quote, non solo accuratezza.  
- Void in crescita → calendario ATP/WTA con molti walkover/ritiri.
- CLV medio alto con copertura molto bassa → possibile falso positivo (pochi closing disponibili).

### Limiti noti

- Senza pubblicazioni, pagina vuota (normale se live disabilitato).  
- Distribuzione “per modello” dipende da cosa è stato effettivamente pubblicato.

---

## Dashboard abbonamenti — `/subscriptions-dashboard`

### A cosa serve

Vista amministrativa dedicata al ciclo abbonamenti: utenti `Free`/`Pro`/`Founder`, stato sottoscrizioni (`active`/`trialing`/`suspended`/`canceled`/`expired`), scadenze, pagamenti falliti, entrate mensili, conversione Free→Pro, churn, storico eventi ed export CSV.

### Quando aprirla

- Controllo giornaliero salute abbonamenti e trend revenue.
- Triage rapido utenti con pagamento fallito o in scadenza.
- Audit operazioni manuali (sospensioni, riattivazioni, cancellazioni).

### Cosa NON fa / con cosa non confonderla

- Non sostituisce la gestione analytics del bot Telegram.
- Non modifica automaticamente piani o prezzi: le azioni manuali sono esplicite per singolo abbonamento.
- L’export CSV rispecchia i filtri correnti della tabella utenti.

### Filtri e controlli

| Controllo | Cosa fa | Nota |
|-----------|---------|------|
| Ricerca | Filtra per username / external ref / telegram id | Testo libero |
| Piano | Free, Pro, Founder | “Tutti” di default |
| Stato | trialing/active/suspended/canceled/expired | Per lifecycle |
| Pagamento fallito | Solo con/solo senza fallimenti | Utile per recovery billing |
| Scadenza entro X giorni | Filtra utenti prossimi alla scadenza | Es. 7 o 30 |
| Cancellazione a fine periodo | Sì/No | Cross-check con churn |
| Solo in prova | Mostra solo trialing | Funnel conversione |
| Esporta CSV | Scarica la lista filtrata | Operazione auditata |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Utenti Free / Pro / Founder | Distribuzione base utenti | Mix commerciale corrente |
| Abbonamenti attivi / in prova | Carico attuale pagante e trial | Monitora saturazione trial |
| Scadenze <= 30g | Utenti a rischio uscita breve | Azioni proattive retention |
| Pagamenti falliti (30g) | Eventi billing failed recenti | Priorità operativa |
| Entrate mese | Ricavi del mese corrente (eventi succeeded) | Confronta trend mensile |
| Conversione Free->Pro | Utenti passati da Free a Pro / base Free | Efficienza funnel |
| Churn (30g) | Utenti terminati / base attiva 30g fa | Stabilità base pagante |
| Storico eventi | Timeline unificata payment + azioni admin | Audit e diagnosi |

### Azioni manuali

- **Sospendi**: blocca accesso mantenendo tracciamento motivazione.
- **Riattiva**: ripristina stato attivo/trialing se coerente con scadenza.
- **Cancella**: termina manualmente l’abbonamento (operazione confermata UI).

Ogni azione manuale viene registrata in audit (`admin_audit_log`) con admin, target e contesto.

### Esempio pratico

1. Filtro `Pagamenti falliti = Solo con fallimenti`.
2. Esamina utenti in `Pro` con scadenza ravvicinata.
3. Se necessario sospendi/riattiva manualmente dal tabellone.
4. Esporta CSV per condivisione con team supporto/finance.

### Limiti noti

- KPI conversion/churn sono calcolati su logica applicativa e dipendono dalla qualità storica degli eventi.
- In ambienti molto grandi conviene usare filtri prima dell’export CSV.

---

## Bot Telegram — `/telegram-bot`

### A cosa serve

Analytics **admin** sull’uso del bot: quanti comandi, quali azioni, errori, serie giornaliera e log accessi recenti.

### Quando aprirla

- Dopo deploy bot o campagna inviti beta.  
- Se un utente segnala “il bot non risponde” (filtra per user ID).  
- Per vedere quali comandi (/schedine, /partite, …) sono più usati.

### Cosa NON fa / con cosa non confonderla

- **Non** gestisce whitelist (→ **Utenti beta Telegram**).  
- **Non** mostra contenuto messaggi privati oltre metadati evento.  
- Metriche tip/ROI → dashboard live o report settimanale.

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Da / A | Periodo eventi | Default 30 giorni |
| Comando / azione | Es. `/schedine` | Match parziale |
| User ID / Username | Utente specifico | ID numerico Telegram |
| Paginazione accessi | 50 eventi per pagina | — |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Eventi totali / unici / oggi | Volume utilizzo | Picchi in giornata match |
| Comando più usato | Top action | Guida priorità manutenzione |
| Tabella comandi | Conteggio per azione | Confronta /schedine vs /statistiche |
| Serie giornaliera | Barre ultimi 5 giorni visibili | Pagina avanti/indietro |
| Accessi recenti | Log riga per riga | Esito **errore** → messaggio colonna Errore |

### Esempio pratico

1. Filtra ultima settimana, azione `/schedine`.  
2. Se errori &gt; 0, apri righe con Esito **errore** e correlazione con **Report aggiornamento**.  
3. Confronta utenti unici con **Utenti beta** attivi.

### Segnali da tenere d’occhio

- Errori ripetuti stesso comando → API backend o rate limit.  
- Eventi oggi = 0 ma utenti attivi → bot non in esecuzione.  
- Picco comandi senza correlato tip live → solo consultazione.

### Limiti noti

- Richiede bot avviato e tabella analytics migrata.  
- Rate limit anti-abuso non distingue utente sospeso vs errore tecnico.

---

## Utenti beta Telegram — `/telegram-users`

### A cosa serve

Gestione **whitelist** beta: invito, attivazione, sospensione, blocco; visibilità su termini accettati e preferenze notifiche.

### Quando aprirla

- Nuovo tester chiede accesso dopo `/start`.  
- Moderazione (spam, abuso) → sospendi o blocca.  
- Verifica chi ha accettato condizioni prima di abilitare `/schedine`.

### Cosa NON fa / con cosa non confonderla

- **Non** sostituisce analytics comandi (**Bot Telegram**).  
- **Non** invia messaggi massivi (notifiche = job backend).  
- Feedback utente → pagina **Feedback Telegram**.

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Ricerca | id, username, nome, origine invito | — |
| Stato | invited / active / suspended / blocked | Filtra **invited** per attivazioni pendenti |
| Invita utente | Form con telegram_user_id | Obbligatorio ID numerico; username opzionale |
| Azioni riga | Attiva / Sospendi / Blocca | Blocco permanente vs sospensione temporanea |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Status | Stato accesso | Solo **active** + termini ok usano comandi pronostici |
| Termini | Accettati sì/no + versione | Richiedi `/accetta_condizioni` se pending |
| Notifiche | Preferenze push | Master e tipi (pronostici, risultati, …) |
| first/last access | Engagement | Retention settimanale in report beta |

### Esempio pratico

1. Cerca username `@mario`.  
2. Se **invited**, clic **Attiva** dopo verifica identità.  
3. Se non accetta termini, guida l’utente a `/accetta_condizioni`.

### Segnali da tenere d’occhio

- Molti **invited** mai attivati → funnel onboarding.  
- Active con notifiche off → calo engagement bot.  
- Stesso ID re-invited dopo block → valuta policy.

### Limiti noti

- Whitelist disabilitata in config → tutti possono restare in attesa diversa.  
- `chat_id` necessario per push; può mancare se utente non ha mai completato `/start`.

---

## Feedback Telegram — `/telegram-feedback`

### A cosa serve

Inbox feedback inviati con `/feedback`: categoria, voto 1–5, testo libero e workflow stati (new → reviewing → resolved/rejected).

### Quando aprirla

- Routine settimanale qualità prodotto.  
- Dopo release, per triage bug vs suggerimenti.  
- Chiudere loop con utente (resolved/rejected).

### Cosa NON fa / con cosa non confonderla

- **Non** risponde in automatico in chat (gestione manuale fuori UI).  
- **Non** include messaggi non inviati via flusso `/feedback`.

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Ricerca | id, utente, testo | — |
| Stato | new / reviewing / resolved / rejected | Parti da **new** |
| Categoria | bug, content, ux, feature, access, other | Priorità bug in rosso operativo |
| Azioni | Cambia stato | reviewing mentre indagini |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Rating | 1–5 stelle | Medio nel report settimanale |
| Categoria | Tassonomia problema | Trend UX vs content |
| Messaggio | Testo utente | — |
| Stato | Workflow | Non lasciare new > 7 giorni |

### Esempio pratico

1. Filtra **new** + categoria **bug**.  
2. Segna **reviewing**, riproduci, apri ticket/fix.  
3. **Resolved** se rilasciato fix; **rejected** se fuori scope (nota interna).

### Segnali da tenere d’occhio

- Picco **access** → problemi whitelist/termini.  
- Rating ≤2 su **content** → revisione copy bot/UI.  
- Stesso utente molti feedback → contatto diretto.

### Limiti noti

- Nessuna allegato immagine in tabella (solo metadati testuali).

---

## Report settimanale beta — `/weekly-beta-report`

### A cosa serve

Snapshot **settimana ISO (lun–dom)** con KPI utenti, retention, comandi bot, tip live, pipeline, notifiche e feedback; confronto **week-over-week** e storico report salvati.

### Quando aprirla

- Lunedì mattina (job automatico o generazione manuale).  
- Riunione stakeholder beta.  
- Archivio trend multi-settimana (tabella storico).

### Cosa NON fa / con cosa non confonderla

- **Non** sostituisce drill-down giornaliero (**Dashboard beta live**).  
- ROI settimanale tip live headline = **Vincitore partita**; tabella `by_market` per 1° set / O/U senza mischiare.  
- ROI tip live ≠ ROI schedine simulate.  
- Generazione **force** sovrascrive snapshot esistente stessa settimana.

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Genera ultima settimana | Crea report settimana completa precedente | Invia Telegram admin se configurato |
| Rigenera (force) | Ricalcola e sostituisce | Dopo fix dati storici |
| Apri (storico) | Carica report passato | Confronto lungo periodo |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Utenti totali / attivi / nuovi | Base utenti beta | “Attivi” = uso nel periodo |
| Retention W1 | Coorte settimana precedente | Hint “vs prec.” in punti percentuali |
| Eventi bot / per azione | Engagement | Calo retention + calo eventi = churn |
| Tip pubblicati / ROI / drawdown | Performance live settimana | Campione corto se pochi tip |
| Pipeline run falliti | Salute aggiornamento | Correla con errori report aggiornamento |
| Notifiche fallite | Push non consegnate | Controlla bot/token/chat_id |
| Feedback totali / rating | Qualità percepita | Incrocia con pagina Feedback |
| Telegram (storico) | Stato invio riepilogo admin | sent / failed / skipped |

### Esempio pratico

1. Clic **Genera ultima settimana** il lunedì.  
2. Leggi hint “vs prec.” su ROI e utenti attivi.  
3. Se ROI ↓ ma hit rate stabile, apri **Statistiche live** filtrando quella settimana.  
4. Se notifiche fallite ↑, verifica **Utenti beta** (chat_id, stati).

### Segnali da tenere d’occhio

- Retention W1 sotto soglia interna.  
- `pipeline_errors` WoW positivo.  
- Report Telegram **failed** → controllare log backend.

### Limiti noti

- Settimana in fuso Europe/Rome (backend).  
- Tip live nella settimana possono essere pochi (ROI volatile).

---

## Report aggiornamento — `/global-update-report`

### A cosa serve

Dettaglio **ultima run** “Aggiorna tutto”: mercati aggiornati (Vincitore partita, 1° set, O/U), fasi, errori, warning, conteggi partite e schedine.

### Quando aprirla

- Dopo ogni run, soprattutto se sidebar mostra “N errori”.  
- Debug previsioni mancanti o schedine non aggiornate.  
- Verifica stato walk-forward osservabile (se abilitato in run).

### Cosa NON fa / con cosa non confonderla

- **Non** elenca singole partite “Da generare” (vedi **Partite**).  
- Mostra solo **ultima** run (non storico completo in UI).  
- Walk-forward qui = solo riepilogo; dettaglio fold in **Walk-forward**.  
- **Non** parla di versioni modello (`v*`): in UI vedi solo **mercati**.

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Ricarica | Ri-legge ultima run | Dopo fix e nuova run |
| (Sidebar) Aggiorna tutto / Annulla | Avvia o ferma pipeline | Un run alla volta |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Stato run | completed / completed_with_errors / failed | Parziale successo possibile |
| Mercati ok / falliti / saltati | Per mercato aggiornato | Isola quale mercato non ha girato |
| Partite processate / Schedine | Volume lavoro | Zero schedine → pochi PLAY o errore |
| Tabella mercati | Match + tip 1° set / O/U | Conteggio previsioni/tip per mercato |
| Fasi | Import, predict, slips, mercati extra… | Durata anomala → collo bottiglia |
| Errori / Warning | Testo libero | Clic from sidebar = stesso contenuto |
| Walk-forward (pannello) | Solo osservabilità | Non attiva modello pubblico |

### Esempio pratico

1. Run con “2 errori” → apri report → tabella mercati → identifica quale mercato ha fallito.  
2. Se errore import API tennis → verifica chiave e timeout.  
3. Se solo i mercati extra falliscono, Match e schedine possono restare utilizzabili.

### Segnali da tenere d’occhio

- `completed_with_errors` ripetuto stessa combo → modello/dataset mancante su disco.  
- Zero partite processate → import fallito del tutto.  
- Warning ripetuti quote → copertura v3 bassa.

### Limiti noti

- Nessun confronto tra run storiche in UI.  
- Run interrotta può risultare `cancelled` o `interrupted` al restart backend.

---

# BACKTEST / OPS

## Statistiche previsioni — `/prediction-stats`

### A cosa serve

Accuratezza e KPI per **mercato** (tab Match / 1° set / O/U). Sul Vincitore partita usa le previsioni operative; su 1° set e O/U usa i tip del registro live.

### Quando aprirla

- Confrontare i tre mercati sullo storico.  
- Monitorare trend accuracy / hit rate.  
- Capire se un mercato performa peggio degli altri.

### Cosa NON fa / con cosa non confonderla

- Match = previsioni operative; 1° set / O/U = tip pubblicati (non tutte le predizioni intermedie).  
- ROI Match = simulazione flat stake, non criterio PLAY.  
- Non sostituisce **Statistiche live** (tipbook ufficiale) né **Walk-forward**.

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Tab mercato | Match / 1° set / O/U | Un mercato alla volta; niente `v*` |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Accuracy / Hit rate | Prese ÷ risolte | Ignora pending/void |
| Profitto / ROI | Teorico o tipbook | Dipende dal tab mercato |
| Andamento per giorno | Solo Match | Serie temporale operativa |

### Esempio pratico

1. Tab **Vincitore partita** → accuracy e ROI teorico giornalieri.  
2. Tab **Vincitore 1° set** → tip live di quel mercato.  
3. Se un mercato è vuoto → verifica pubblicazione / global update.

### Segnali da tenere d’occhio

- Pending alti → import risultati in ritardo.  
- Accuracy cala su giorni recenti → drift o calendario più duro.  
- Poche previsioni con quota → ROI giornaliero vuoto.

### Limiti noti

- Non distingue superficie/torneo (usa **ROI per segmento** backtest).  
- Include tutte le partite prese in calendario, non solo quelle “giocabili”.

---

## Statistiche schedine — `/betting-slip-model-stats`

### A cosa serve

Hit rate delle **pick per mercato** (Match / 1° set / O/U) e esito complessivo delle schedine nel periodo scelto. Nessuna colonna versione modello in UI.

### Quando aprirla

- Capire quale mercato contribuisce di più alle gambe vinte/perse.  
- Valutare se le schedine multi-mercato rendono nel lungo periodo.  
- Ranking periodo per ROI o win rate schedina.

### Cosa NON fa / con cosa non confonderla

- **Non** mostra singole schedine (→ **Consiglio schedina**).  
- **Non** è performance live tipbook.  
- Pending esclusi dalle percentuali in header.  
- Le schedine possono mescolare mercati: la tabella mercati è sulle **pick**, non sulle schedine intere.

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Ultimi 30 giorni / All time / Date manuali | Periodo | All time per decisione strategica |
| Simula puntata (€) | Scala profitto/ROI | Default 10 € |
| Ordinamento colonne | Per win rate, ROI o # schedine | Clic intestazione |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Pick per mercato | Hit rate gambe per Match / 1° set / O/U | Confronta i tre mercati |
| % schedine | Win rate intero coupon | Più basso dell’hit pick singolo |
| Profitto / ROI | Teorico su stake simulato | Una schedina persa = −stake intero |

### Esempio pratico

1. Periodo **ultimi 30 giorni**.  
2. Guarda **Pick per mercato**: se O/U ha hit basso, rivedi i profili.  
3. Poi guarda esito schedine complessivo (ROI).
4. Allinea scelta con profilo rischio (win rate vs ROI).

### Segnali da tenere d’occhio

- ROI alto su &lt;15 schedine risolte → rumore.  
- Hit pick alto ma win rate schedine basso → correlazione negativa tra gambe.  
- Pending accumulati → giornate recenti non chiuse.

### Limiti noti

- Non separa profili (Play sicura vs Mista) → solo totale per modello.  
- ROI assume stake fisso per schedina.

---

## Walk-forward — `/walk-forward`

### A cosa serve

Validazione **temporale multi-fold** separata per **Vincitore partita**, **Vincitore 1° set** e **Over/Under Games** (default: modelli live; le nuove run non includono più le versioni archiviate). Non modifica i modelli in produzione.

### Quando aprirla

- Prima di promuovere una nuova versione modello.  
- Dopo cambio dataset o feature, per verificare stabilità nel tempo.  
- Se sospetti overfitting sull’holdout statico.

### Cosa NON fa / con cosa non confonderla

- **Non** aggiorna il modello pubblico né le previsioni live.  
- **Non** è il registro tip (**Statistiche live**).  
- Risultati OOS alimentano **Calibrazione** e analisi **Fasce probabilità** / **ROI segmento** (sorgente walk-forward).

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Modalità Expanding / Rolling | Finestra training crescente vs fissa | Expanding = più dati nel tempo; rolling = adattamento recente |
| Avvia walk-forward | Nuova run multi-mercato in background | Una run attiva alla volta; barra avanzamento + **Annulla** |
| Selezione run (tabella) | Storico ultime 20 run | Clic riga per dettaglio; colonna Mercati (non v*) |
| Tab mercato | Navigazione per mercato (Match / 1° set / O/U) | Ogni mercato mostra esclusivamente i propri fold |
| Includi archivio | Mostra fold storici v1–v3 su run vecchie | Spento di default |
| Filtro contender | Tabella fold filtrata per benchmark ufficiale o modello ML | Contender: `market_favorite`, `market_no_vig`, `atp_ranking`, `elo`, `logistic_regression`, `random_forest` |
| Paginazione giorno test | Naviga i fold per giorno/finestra test | Evita confronto visivo tra periodi lontani |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Fold index | Numero fold cronologico | Trend accuracy ↓ sugli ultimi fold = drift |
| Train / Test date | Intervalli temporali | Verifica embargo (giorni tra train e test) |
| Righe train/test | Campione | Fold saltati se troppo pochi dati |
| Accuracy / Log Loss / Brier | Performance probabilistica/classificazione | Confronto ufficiale su campione comune |
| ROI / Yield / Drawdown / CLV | Performance betting-oriented | CLV può essere non disponibile in OOS offline |
| Sample mismatch | Segnala righe escluse per confronto comune | Se `Warning`, apri tooltip e verifica `rows_common_official` |
| Leakage flags | Segnali sospetti feature future | **Obbligatorio** investigare se &gt;0 |
| Stato fold | skipped / error | Non contare nel benchmark |
| Aggregato benchmark ufficiali | Media per contender e mercato | Vista sintetica multi-fold |
| JSON versions_detail | Dettaglio tecnico completo run | Holdout **non** sovrascritto dalla run |

### Esempio pratico

1. Avvia run **expanding**, attendi completamento (poll ~12s).  
2. Resta sul tab **Vincitore partita** e filtra **logistic_regression** (o ensemble).  
3. Controlla ultimi 3 fold: accuracy stabile? leakage vuoto?  
4. Se ok, lancia **Calibrazione** sulla stessa base temporale.

### Segnali da tenere d’occhio

- Molti fold **skipped_insufficient_data** → dataset troppo corto.  
- Leakage su feature ranking → bug pipeline feature.  
- Run **failed** in Docker → montare volume dataset (`PROCESSED_HOST_PATH`).

### Limiti noti

- Run lunghe; restart backend marca run attive come interrotte.  
- Parametri finestra (train/test/step) da config/job, non tutti in UI.

---

## Calibrazione — `/calibration`

### A cosa serve

Verifica separatamente se le **probabilità** dei modelli live di **Vincitore partita**, **Vincitore 1° set** e **Over/Under Games** corrispondono alle frequenze reali (reliability curve), confrontando probabilità **grezza**, **Platt scaling** e **isotonic regression** su dati out-of-sample del walk-forward.

### Quando aprirla

- Dopo walk-forward, prima di fidarti delle probabilità per stake sizing.  
- Se in live il hit rate a 70% predetto ≠ ~70% osservato.  
- Per decidere se investire in calibrazione post-modello (non è auto-attiva).

### Cosa NON fa / con cosa non confonderla

- **Non** attiva calibratori sulle previsioni live automaticamente.  
- **Non** è ROI per segmento ( anche se ECE alto spiega ROI deluso ).  
- Richiede predizioni OOS (run calibrazione rilancia walk-forward se necessario).

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Avvia calibrazione | Nuova run multi-mercato in background | Vincitore partita, Vincitore 1° set e Over/Under restano separati; barra avanzamento + Annulla |
| Tab mercato | Navigazione Match / 1° set / O/U | Ogni mercato mostra esclusivamente i propri risultati |
| Includi archivio | Mostra risultati storici v1–v3 | Spento di default |
| Run (select) | Scegli storico run | — |
| Modello | Filtra risultati | Ensemble / LR / RF |
| Metodo grafico | raw / platt / isotonic | Confronta curve |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| **ECE** | Expected Calibration Error | Più basso = probabilità più affidabili |
| **MCE** | Maximum bin error | Peggior fascia |
| **Brier / Log loss** | Qualità probabilistica globale | Confronto metodi nella tabella |
| Reliability curve | Asse X = prob. predetta, Y = frequenza osservata | Vicino alla diagonale = calibrato |
| Gap per fascia | mean_predicted − mean_actual | Sistematico positivo = sovrastima |
| Punti arancioni | Campione insufficiente in bin | Non usare per decisione |
| Δ Brier vs grezzo | Miglioramento Platt/isotonic | Se ~0, calibrazione non serve |

### Esempio pratico

1. Completa il walk-forward multi-mercato sui modelli live.
2. Avvia calibrazione, apri run completata.  
3. Se ECE grezzo 0.08 e Platt 0.04 → Platt aiuta; valuta deploy manuale.  
4. Fascia 50–60% con gap +10pp → evita stake alti su quel bin.

### Segnali da tenere d’occhio

- MCE alto su una sola fascia → outlier strutturale (es. grass).  
- Isotonic migliora train ma non OOS → overfit calibratore.  
- `leakage_flags` nel result → invalida conclusioni.

### Limiti noti

- Artefatti pickle salvati su disco; non versionano modello pubblico.  
- Campioni OOS piccoli → bin unreliable (arancioni).

---

## Fasce probabilità — `/probability-bands`

### A cosa serve

Analizza hit rate, gap calibrazione, profitto e ROI per **fasce** di probabilità o di **edge**, con intervalli di confidenza. Sorgente selezionabile: live, walk-forward OOS o backtest.

### Quando aprirla

- Capire se conviene puntare solo certe fasce (es. prob 55–65% o edge &gt;5%).  
- Confrontare probabilità grezza vs calibrata (sorgente offline).  
- Validare strategia PLAY su storico live.

### Cosa NON fa / con cosa non confonderla

- Live = solo tip **pubblicati** del **mercato selezionato** (tab Match / 1° set / O/U), non tutte le previsioni Partite.  
- Backtest/walk-forward = solo **Vincitore partita** OOS ≠ performance tipbook reale (slippage, selezione PLAY).  
- Non sostituisce **Calibrazione** (qui KPI betting per bin, non solo reliability).

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Tab Mercato (solo Live) | Match / 1° set / Over-Under | Default Match; KPI non misti |
| Sorgente Live / Walk-forward / Backtest | Popolazione dati | Live per ops; WF per design strategia |
| Dimensione fascia Probabilità / Edge | Asse binning | Edge utile per policy value |
| Tipo prob. (offline) | raw / platt / isotonic | Disabilitato su edge |
| Versione / Modello (offline) | Combo ML match-winner | Default **v4** / voting_ensemble |
| Da / A | Periodo | 180 giorni default |
| N. fasce / Min. campione | Granularità vs robustezza | Min **30** consigliato |
| Confronta raw/platt/isotonic | Tabelle parallele | Solo prob offline |
| Raggruppa per fold / periodo | Drill-down | Fold solo walk-forward |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| N (chiusi) | Tip nella fascia | Basse → riga **Basso** campione |
| Hit rate + IC 95% | Wilson | IC largo = incertezza |
| Prob. prevista / osservata / Gap cal. | Solo dimensione probabilità | Gap positivo = modello ottimista |
| Quota / Edge medi | Context mercato | — |
| Profitto / ROI / Yield | Stesse regole live | Void esclusi da hit/ROI |
| Campione OK/Basso | `insufficient_sample` | Non over-interpretare righe gialle |

### Esempio pratico

1. Sorgente **Live**, dimensione **Edge**, ultimo anno.  
2. Trova fascia edge 5–10% con ROI positivo e N≥50.  
3. Passa a **Partite** e verifica quanti match odierni cadono lì (margine 2%).  
4. Ripeti con sorgente **Walk-forward** per vedere se pattern regge OOS.

### Segnali da tenere d’occhio

- ROI positivo solo su fasce a campione basso.  
- Gap calibrazione crescente alle probabilità alte.  
- Note in pannello info (backend) su dati mancanti.

### Limiti noti

- Live non applica probabilità calibrate (sempre raw).  
- Troppi bin con `n_bins` alto → molte righe gialle.

---

## ROI per segmento — `/segment-roi`

### A cosa serve

Performance per **segmento** (superficie, torneo, circuito, livello, turno, favorito/sfavorito, fascia quota, bookmaker, modello, versione, periodo): hit rate, ROI, yield, drawdown e intervalli di confidenza.

### Quando aprirla

- Decisioni operativi: “puntiamo sfavoriti su clay in live?”.  
- Monitoraggio torneo specifico (es. slam vs challenger).  
- Confronto bookmaker (quote medie aggregate).

### Cosa NON fa / con cosa non confonderla

- Segmento **torneo** live può avere campione minuscolo per evento singolo.  
- **Bookmaker** su live = aggregato quote medie, non singolo operator.  
- Walk-forward/backtest misura potenziale storico **match-winner**, non slippage esecuzione.  
- Live: un mercato alla volta (stessi tab di Fasce probabilità).

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Tab Mercato (solo Live) | Match / 1° set / Over-Under | Default Match; KPI non misti |
| Sorgente | Live / Walk-forward / Backtest | Come Fasce probabilità |
| Segmento | Dimensione analisi | Inizia da **superficie** o **favorite_role** |
| Versione / Modello (offline) | Filtra OOS match-winner | Default **v4** / voting_ensemble |
| Min. campione segmento | Soglia `insufficient_sample` | Default 30; alza per report executive |
| Raggruppa per fold / periodo | Tabelle aggiuntive | Trend stagionale |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Hit rate + IC | Wilson | Confronta segmenti sovrapponendo IC |
| ROI + IC ROI | Bootstrap | ROI positivo con IC che include 0 → non significativo |
| Max drawdown | Per segmento (tip chiusi del segmento) | Rischio tail del segmento |
| Edge medio | Valore al publish/simulazione | Segmenti ad alto edge ma ROI negativo → odds realizzate basse |
| Campione Basso | Evidenziazione riga | Escludi dal decision making |

### Esempio pratico

1. Live, segmento **superficie**, 6 mesi, min campione 30.  
2. Clay ROI +8%, Hard ROI −3% (entrambi OK campione).  
3. Drill **favorite_role** su Clay: sfavoriti ROI positivo?  
4. Conferma su walk-forward prima di marketing “specialty clay dogs”.

### Segnali da tenere d’occhio

- Torneo singolo con ROI estremo e N=5.  
- Livello torneo live incompleto → segmento “unknown”.  
- Drawdown segmento &gt; profitto totale segmento.

### Limiti noti

- Metadati mancanti su partite minori → segmenti “unknown”.  
- IC ROI richiede campione sufficiente; altrimenti vuoto.

---

# Extra

## Login — `/login`

### A cosa serve

Accesso **amministratore** alla dashboard (JWT). Senza login tutte le route protette reindirizzano qui.

### Quando aprirla

- Prima sessione del giorno o dopo **Esci**.  
- Se token scaduto (sessione lunga, default ore configurabili backend).

### Cosa NON fa / con cosa non confonderla

- **Non** è login utenti Telegram beta.  
- Credenziali ≠ `SERVICE_API_KEY` (uso bot/server-to-server).

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Username / Password | Autenticazione admin | Primo admin da env se DB vuoto |
| Accedi | Ottiene token sessione | Dopo redirect a `/predictions` o pagina richiesta |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Messaggio errore | Login fallito | Verifica `ADMIN_JWT_SECRET` e utente esistente |

### Esempio pratico

1. Apri sito → login.  
2. Se fallisce, controlla backend avviato e variabili admin in `.env`.  
3. Dopo login, sidebar mostra username.

### Segnali da tenere d’occhio

- HTTP 429 → rate limit login; attendi `Retry-After`.

### Limiti noti

- Un solo ruolo admin in UI; no RBAC granulare in frontend.

---

## Aggiornamento globale — controllo sidebar

*(Non è una route dedicata; pannello in alto nella sidebar.)*

### A cosa serve

Esegue in sequenza import partite recenti, import prossime partite, generazione previsioni per **ogni** combo modello/versione su disco e aggiornamento schedine. È il battito cardiaco operativo giornaliero.

### Quando aprirla

- Inizio giornata prima di Partite/Schedine.  
- Dopo lungo downtime o errori import API.  
- Quando sidebar segnala run completata e pagine non si aggiornano (refresh manuale pagina).

### Cosa NON fa / con cosa non confonderla

- **Non** sostituisce job cron notturno (stessa pipeline, origine diversa).  
- **Non** lancia automaticamente walk-forward completo (salvo flag backend dedicato).  
- Errori combo ≠ stato “Da generare” singola partita.

Dettaglio fasi: [GUIDA_UTENTE.md — Aggiornamento globale](GUIDA_UTENTE.md#aggiornamento-globale).

### Filtri e controlli

| Controllo | Cosa fa | Valore consigliato / nota |
|-----------|---------|---------------------------|
| Aggiorna tutto | Avvia run `force=true` | Disabilitato se run in corso |
| Annulla | Richiesta stop cooperativo | Non istantaneo su fase lunga |
| Link N errori | Apre **Report aggiornamento** | Investigare sempre se &gt;0 |
| Pill fase / % | Stato corrente | — |

### Metriche e colonne principali

| Nome | Significato | Come interpretarlo |
|------|-------------|-------------------|
| Ultimo completamento | Timestamp + origine manual/cron | — |
| Fase corrente | Es. import, predict, slips | Stima tempo residuo |
| Conteggio errori | Run `completed_with_errors` | Parziale successo |

### Esempio pratico

1. Clic **Aggiorna tutto** alle 9:00.  
2. Attendi pill **completed** (o completed_with_errors).  
3. Apri **Partite** → verifica tab Da giocare popolata.  
4. Se errori, **Report aggiornamento** → fix → ri-run.

### Segnali da tenere d’occhio

- Run che non finisce (&gt;30 min) → annulla e controlla log API.  
- “Già in esecuzione” → un solo run globale alla volta.  
- Import oggi = No dopo run ok → verificare API tennis.

### Limiti noti

- Aggiorna **tutte** le versioni su disco (più lento del job v2-only CLI).  
- Rate limit endpoint costoso se click ripetuti.

---

## Flusso operativo consigliato (riepilogo)

1. **Login** → **Aggiorna tutto** (sidebar).  
2. **Dashboard beta live** — sanity check pipeline e tip oggi.  
3. **Partite** — selezione PLAY; **Consiglio schedina** — coupon.  
4. **Statistiche live** / **ROI per segmento** (live) — review performance.  
5. Settimanale: **Report settimanale beta** + **Bot Telegram** / **Feedback**.  
6. Mensile/strategico: **Walk-forward** → **Calibrazione** → **Fasce probabilità** / **ROI segmento** (OOS).

Per domande generali e avvio stack: [GUIDA_UTENTE.md](GUIDA_UTENTE.md).
