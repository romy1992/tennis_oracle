# Guida utente — tennis_oracle

Questa guida spiega **a cosa serve** il progetto e **come usarlo**, senza entrare nei dettagli del codice.

Per la documentazione tecnica (classi, metodi, API, ML) vedi [README.md](../README.md).  
Per lo scheduling giornaliero vedi [SCHEDULING.md](SCHEDULING.md).

---

## Cos’è tennis_oracle?

**tennis_oracle** è un’applicazione che:

1. Scarica partite di tennis da un’API esterna
2. Salva tutto in un database PostgreSQL
3. Usa modelli di machine learning per stimare chi può vincere
4. Confronta le probabilità del modello con le quote dei bookmaker
5. Mostra tutto in un’interfaccia web (e opzionalmente via bot Telegram)

In pratica ti aiuta a:

- vedere le **partite in arrivo** con pronostico
- valutare se una quota ha **valore** rispetto al modello
- consultare **schedine consigliate**
- controllare le **statistiche** di quanto i modelli e le schedine hanno indovinato

> Non è una garanzia di vincita. I modelli stimano probabilità; il mercato delle scommesse resta rischioso.

---

## Cosa trovi nell’interfaccia web

Dopo aver avviato frontend e backend (vedi [Avvio rapido](#avvio-rapido)), apri il sito (di solito `http://localhost:5173`).

Alla prima apertura ti viene chiesto di **accedere come amministratore** (username e password configurati sul server). Senza login non puoi usare la dashboard. In basso nella sidebar trovi il tuo utente e il pulsante **Esci**.

Nel menu laterale trovi:

| Voce | A cosa serve |
|------|----------------|
| **Dashboard beta live** | Panoramica operativa LIVE: stato pipeline, tip pubblicati oggi, aperti/chiusi, KPI e drawdown, utilizzo bot, errori recenti e completezza dati. Filtri per periodo, modello, torneo, superficie e fascia di quota. Le metriche di training/backtest restano in sezioni separate |
| **Partite** | Elenco partite con pronostico, quota void e stato valore (PLAY / BORDERLINE / NO BET) e stato partita (da giocare, rinviata, annullata, …) |
| **Consiglio schedina** | Fino a 9 schedine per giorno a difficoltà crescente: 3 solo Play, 3 Play+Borderline, 3 miste |
| **Statistiche schedine** | Confronto risultati delle schedine tra modelli/versioni |
| **Statistiche previsioni** | Accuratezza e metriche delle previsioni operative nel tempo (non il registro pubblicazioni) |
| **Storico pubblicazioni** | Registro immutabile dei pronostici pubblicati (versione, hash, fonte); dopo l’inizio partita non si modifica, le correzioni creano una nuova versione |
| **Statistiche live** | Performance dei tip pubblicati: hit rate, stake, profitto, ROI/yield, drawdown, serie e distribuzioni. Solo registro immutabile; non confondere con training o backtest |
| **Report aggiornamento** | Esito dell’ultima run “Aggiorna tutto”: errori, warning, fasi e combo modello |
| **Bot Telegram** | Solo admin: accessi e comandi usati sul bot (KPI, filtri per data/utente/comando, breakdown giornaliero, storico) |
| **Utenti beta Telegram** | Solo admin: whitelist utenti del bot (ricerca, invito, attivazione, sospensione, blocco; stato termini, origine invito e preferenze notifiche) |
| **Feedback Telegram** | Solo admin: inbox dei feedback inviati dal bot (categoria, voto, messaggio; stati new / reviewing / resolved / rejected) |
| **Report settimanale beta** | Solo admin: snapshot KPI della settimana (utenti, retention, comandi, tip live, ROI/drawdown, errori pipeline, notifiche fallite, feedback) con confronto rispetto alla settimana precedente; generazione manuale o job del lunedì |

In alto nella sidebar c’è anche il controllo **Aggiornamento globale**: importa partite, genera previsioni per tutti i modelli disponibili e aggiorna le schedine. Se compaiono errori (es. “4 errori”), il conteggio è cliccabile e apre **Report aggiornamento**.

### Come scegliere modello e versione

Nelle pagine puoi scegliere:

- **Versione modello**: `v1`, `v2`, `v3` (default in interfaccia e bot: **v3**); la scelta resta salvata nel browser
- **Tipo modello**: regressione logistica o random forest

In sintesi:

- **v1 / v2**: il modello **non usa le quote** per predire; le quote servono dopo per edge e value bet
- **v3**: modello **consapevole delle quote** (solo partite con quote disponibili)

Nota: il job giornaliero da riga di comando, se non specifichi altrimenti, usa ancora **v2**. L’**aggiornamento globale** dalla UI aggiorna invece tutte le combo modello presenti su disco.

### Margine di sicurezza e stati valore

In alto su **Partite** e **Consiglio schedina** trovi il **margine di sicurezza** (default **2%**, editabile). Vale per tutte le partite della pagina. Se lo porti a **0%**, solo le BORDERLINE diventano PLAY; le NO BET restano tali (quota di mercato sotto void).

Per ogni partita con quote e pronostico il sistema calcola:

1. **Quota void** — break-even dalla probabilità del modello (`1 / probabilità`)
2. **Margine di sicurezza** — percentuale sopra la void richiesta per un PLAY (impostata in alto)
3. **Stato valore** — `PLAY` (quota abbastanza sopra void), `BORDERLINE` (sopra void ma sotto il margine), `NO BET` (sotto void)

Nella schedina, la colonna **Media quote bookmakers** è la media delle quote di mercato sul pick (non la quota di un singolo bookmaker). **Non confondere** la colonna Void (quota break-even) con una partita **annullata**: se una partita è cancellata / abbandonata / senza esito scommettibile, il pick in schedina diventa **Annullato** e la sua quota non conta più nella quota combinata.

Il sistema conserva anche uno **storico delle quote pre-match** (apertura, osservazioni successive, momento di pubblicazione del tip, chiusura): ogni rilevamento resta in archivio e non sovrascrive il precedente. Le quote “correnti” usate in Predizioni / Value / Schedine restano quelle aggiornate sull’incontro; lo storico serve per analisi nel tempo (es. CLV).

### Stato partita e schedine ridotte

Nella colonna **Stato** (Partite) e nei dettagli pick (Schedine) vedi anche se la partita è rinviata, annullata, abbandonata, walkover, ecc.

Stati normalizzati della partita:

| Stato | Significato | Singola / pick | Stake e ROI |
|-------|-------------|----------------|-------------|
| Da giocare | Non iniziata | In corso | Stake aperto; non entra nel ROI |
| In corso | Live | In corso | Stake aperto; non entra nel ROI |
| Terminata | Esito con vincitore | Presa / Persa | Conteggiata in profitto e ROI |
| Rinviata | Rimandata | In corso (non annullata) | Stake aperto; non entra nel ROI |
| Annullata / Abbandonata / Esito mancante | Non disputata in modo definitivo | **Annullato** (mai Persa) | Stake restituito; esclusa dal ROI |
| Walkover / Ritiro **con** vincitore | Esito ufficiale | Presa / Persa | Come una partita terminata |
| Walkover / Ritiro **senza** vincitore | Non scommettibile | Annullato | Come annullata |

La **quota void** (break-even del modello) non cambia con lo stato partita: è solo un calcolo di probabilità.

### Statistiche live (registro pubblicazioni)

La pagina **Statistiche live** misura solo i tip salvati nello storico pubblicazioni (non le previsioni operative, non le schedine, non i report di training).

La **Dashboard beta live** riunisce in un’unica vista lo stato della pipeline, i tip di oggi, aperti/chiusi, gli stessi KPI live (incluso drawdown), l’uso del bot, gli errori recenti e indicatori di completezza dati. Se il registro è vuoto, mostra una diagnosi operativa (pubblicazione disabilitata, modello pubblico non configurato, pipeline mai eseguita, nessuna giocata qualificata, errori di pubblicazione). Nel menu e in pagina le aree **LIVE** e **BACKTEST** restano distinte.

Le pubblicazioni automatiche nel registro live avvengono solo per la combinazione modello/versione configurata come pubblica e solo per giocate con decisione **PLAY** (stessi criteri value delle schedine). Di default la scrittura automatica è disabilitata.

In sintesi:

- **Chiusi / aperti / void** seguono le stesse regole di settlement delle altre pagine (annullata = void, non persa)
- **Hit rate** = prese / (prese + perse); i void non entrano
- **Stake totale** = somma degli stake pubblicati; il ROI usa solo lo stake delle scommesse chiuse
- **ROI e yield** (in %) sono uguali: profitto / stake chiuso
- **Max drawdown** e **serie +/-** seguono l’ordine cronologico dei tip chiusi

Regole sulle schedine:

- pick di una partita **non disputata in modo definitivo** → **Annullato** (escluso dalla quota)
- se restano solo pick presi + eventuali annullati → schedina **Presa**, con **quota effettiva** senza le gambe annullate
- rinvio (ancora da giocare) → pick **In corso**, schedina resta in corso
- se **tutti** i pick sono annullati → schedina **Annullata** (puntata restituita / profitto 0)
- walkover / ritiro **con vincitore** → conteggiati come presa/persa normalmente
- le partite annullate o non disputate **non** contano come perse nelle singole né nelle schedine

### Consiglio schedine (difficoltà)

Alla generazione/rigenerazione compaiono tipicamente **9 schedine**:

- **3 Play** — solo pick classificate PLAY
- **3 Play+Border** — mix di PLAY e BORDERLINE
- **3 Miste** — possono includere anche NO BET (più aggressive / rischiose)

Dentro ogni gruppo ci sono varianti (sicura / bilanciata / value). Se i candidati del giorno non bastano, alcune schedine possono mancare o avere meno pick: controlla i messaggi di avviso in pagina.

Usa i tab in alto (versione e modello) per passare da un modello all’altro: vedi una sola lista di schedine alla volta, non entrambe insieme.

### Aggiornamento globale

Il pulsante di aggiornamento globale (se disponibile) fa in sequenza:

1. Import delle partite giocate recenti
2. Import delle prossime partite
3. Generazione previsioni per ogni combinazione modello/versione presente su disco
4. Generazione/aggiornamento delle schedine

Puoi anche **annullare** un aggiornamento in corso. Se è già in esecuzione un altro aggiornamento, di solito ne viene accettato solo uno alla volta.

---

## Avvio rapido

### Requisiti

- Python **3.12**, **3.13** o **3.14**
- Node.js **20.19+** oppure **22.12+** (per il frontend)
- PostgreSQL con database `tennis_db`
- Chiave API tennis (`API_TENNIS_KEY`)

### Con Docker (alternativa)

Se hai Docker e PostgreSQL già sul PC:

1. Copia `.env.example` in `.env` (porte: UI **5173**, API **8000**; DB = Postgres del PC via `host.docker.internal`)
2. Lascia le credenziali nei file di sempre: `backend/.env` e `backend/properties/config.env`
3. Accendi Postgres locale, poi: `docker compose up --build -d` (il container `db-1` non parte)
4. Apri il sito su `http://localhost:5173` (API su `http://localhost:8000`)

Per fermare: `docker compose down` (non usare `-v` se non vuoi toccare un eventuale volume Docker).  
Dopo modifiche al codice in Docker:
- **hot-reload:** `docker compose -f docker-compose.yml -f docker-compose.dev.yml up` — vedi [DOCKER.md](DOCKER.md#modalità-sviluppo-hot-reload)
- **prod-like:** rebuild (`build api` / `build frontend`) — vedi [DOCKER.md](DOCKER.md#dopo-modifiche-al-codice-stack-prod-like-senza-hot-reload)

### Backend

```bash
cd backend
python -m venv .venv
# attiva il virtualenv, poi:
pip install -r requirements.txt
# per sviluppo/test: pip install -r requirements-dev.txt
# poi dalla root del repo: python -m pytest   (suite backend isolata, senza DB/API reali)
# configura .env e/o properties/config.env (parti da config.env.example)
alembic upgrade head
uvicorn src.app.main:app --reload
```

Variabili importanti in `backend/.env` / `backend/properties/config.env`:

- `DATABASE_URL` — connessione PostgreSQL
- `API_TENNIS_KEY` / `API_TENNIS_BASE` — API tennis
- `API_TENNIS_TIMEOUT` — timeout HTTP verso API tennis in secondi (opzionale, default 30)
- `CORS_ORIGINS` — origini frontend consentite
- `ADMIN_JWT_SECRET` — segreto per i token di accesso della dashboard (obbligatorio per il login)
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — usati solo alla prima creazione dell’admin se il database non ne ha ancora uno
- `SERVICE_API_KEY` / `TELEGRAM_SERVICE_API_KEY` — opzionali in locale; se impostati, il bot deve usare la stessa chiave verso l’API (header dedicato, non confondere con il login admin)
- `SERVICE_API_KEY_PREVIOUS` — opzionale, solo durante la rotazione della chiave service
- `TELEGRAM_BOT_TOKEN` — solo se usi il bot (opzionale)

API tipica: `http://localhost:8000`  
Health check: `GET http://localhost:8000/health`  
Readiness (DB): `GET http://localhost:8000/ready`  
Dipendenze / monitoring: `GET http://localhost:8000/deps` (senza dati sensibili)  

In produzione il monitoraggio (log, metriche, alert Telegram admin) si configura come descritto in `docs/MONITORING.md`; non è necessario dalla UI quotidiana.

### Frontend

```bash
cd frontend
npm ci
cp .env.example .env
npm run dev
```

In `frontend/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

Apri il sito e accedi con l’account admin. Se non riesci a entrare, verifica sul backend `ADMIN_JWT_SECRET` e che esista un utente admin (creato al primo avvio da `ADMIN_USERNAME` / `ADMIN_PASSWORD`).

### Bot Telegram (opzionale)

1. Avvia il backend (`alembic upgrade head` serve anche per le tabelle analytics, admin e utenti beta)
2. Imposta in `backend/.env` almeno `TELEGRAM_BOT_TOKEN` (e opzionalmente `TELEGRAM_API_BASE_URL`, `TELEGRAM_SERVICE_API_KEY` allineata a `SERVICE_API_KEY`, versione/modello, margine, whitelist/termini, ecc.)
3. Esegui:

```bash
cd backend
python -m src.app.telegram.bot
```

Comandi attivi: `/start`, `/help`, `/accetta_condizioni`, `/notifiche`, `/feedback`, `/schedine`, `/partite`, `/statistiche`.

Al primo `/start` l’utente viene registrato (con `chat_id` per eventuali notifiche push) e riceve un **menu a pulsanti** (Partite, Schedine, Statistiche, Aiuto). Con whitelist attiva (default) resta in attesa finché un admin non lo **attiva** dalla pagina **Utenti beta Telegram**. Se sono richieste le condizioni d’uso, l’utente deve inviare `/accetta_condizioni` prima di usare `/schedine`, `/partite` e `/statistiche`.

Con `/notifiche` puoi vedere e cambiare le preferenze push (master on/off, pronostici del giorno, riepilogo risultati, giorno senza partite). Le notifiche automatiche partono solo se l’admin ha abilitato il job e l’account è attivo (non sospeso/bloccato).

Con `/feedback` puoi segnalare un problema o un suggerimento: scegli una categoria, dai un voto da 1 a 5, scrivi un messaggio. Per interrompere senza salvare usa `/annulla` (o il pulsante Annulla). Il feedback arriva all’admin nella pagina **Feedback Telegram**.

`/help` mostra una guida rapida. Durante il caricamento di partite/schedine/statistiche compare un messaggio temporaneo; nelle risposte vedi anche l’**ultimo aggiornamento** disponibile, un’avvertenza informativa e (se configurato) un link esterno per feedback. Se non ci sono partite o schedine per oggi, il bot lo dice chiaramente invece di restare in silenzio.

Se invii troppi comandi in poco tempo, il bot ti chiede di attendere qualche secondo (protezione anti-abuso). Lo stesso tipo di limite vale anche per le API del server.

Con `/schedine` ricevi le stesse schedine della pagina **Consiglio schedina** (fino a 9, con Void/Edge/ROI/Valore e stato pick). Se i due motori del giorno producono schedine diverse, il bot le mostra entrambe etichettate con l’accuratezza storica (senza nomi tecnici); se sono uguali ne manda una sola. Il primo messaggio indica data, legenda esiti (verde = Presa, rosso = Persa, grigio = In corso, grigio scuro = Annullata) e legenda valore.

Con `/partite` ricevi le partite di oggi come in pagina **Partite** (Predetto, Conf., Void, Valore, Stato). Anche qui, se i motori danno pronostici diversi li vedi entrambi con etichetta accuratezza; l’intro include data, legende e ultimo aggiornamento.

Con `/statistiche` vedi un riepilogo immagine dell’andamento (partite singole e schedine, con profitto sulle schedine), sempre senza nomi modello.

Nella dashboard web, la voce **Bot Telegram** mostra a te (admin) chi ha usato il bot e quali comandi (filtri per periodo, utente, azione). La voce **Utenti beta Telegram** gestisce whitelist e stati di accesso (invito, attiva, sospendi, blocca). La voce **Feedback Telegram** raccoglie i messaggi inviati con `/feedback` e permette di marcarli come in revisione, risolti o rifiutati. La voce **Report settimanale beta** mostra gli snapshot salvati (e permette di generarne uno per l’ultima settimana completa); un riepilogo viene anche inviato in Telegram all’admin se configurato. Queste pagine non sono visibili agli utenti Telegram.

---

## Flusso quotidiano consigliato

1. Avvia backend e frontend
2. Esegui un **aggiornamento globale** (dalla UI) oppure il job giornaliero (vedi [SCHEDULING.md](SCHEDULING.md))
3. Apri **Partite** per i pronostici del giorno
4. Apri **Consiglio schedina** se vuoi una proposta multipla
5. Controlla le **statistiche** per capire come stanno performando i modelli

Il **job giornaliero** (cron / Docker) e il pulsante **Aggiorna tutto** usano la stessa pipeline. Se usi un database cloud separato, il job può anche **sincronizzare** i dati dal PC locale al cloud (`SYNC_CLOUD` in `properties/config.env`). In caso di interruzione, il job può riprendere dal primo passo fallito.

---

## Domande frequenti

**Come accedo alla dashboard?**  
Serve un account amministratore. Al primo avvio del backend, se `ADMIN_USERNAME` e `ADMIN_PASSWORD` sono impostati e non esiste ancora nessun admin, viene creato automaticamente. Poi apri il sito e fai login.

**Perché alcune partite non hanno pronostico?**  
Mancano dati storici, odds (per `v3`), o l’aggiornamento non è ancora stato eseguito. In **Giocate**, le partite senza previsione salvata restano vuote: il pronostico va generato **prima** che la partita finisca (Aggiorna tutto / job giornaliero). In **Partite**, lo stato **Da generare** indica solo assenza di previsione salvata: non è lo stesso degli errori della run globale.

**Cosa sono gli errori sotto “Aggiorna tutto”?**  
Sono fallimenti della run (import o elaborazione di una combo modello/versione). Aprili da **Report aggiornamento** (o cliccando sul conteggio errori). Una run può risultare “completata con errori” se alcune combo vanno a buon fine e altre no.

**Cosa significa PLAY / NO BET / BORDERLINE?**  
Confronta la quota di mercato con la **quota void** del modello, più il **margine di sicurezza** impostato in alto nella pagina. PLAY = abbastanza sopra void; BORDERLINE = sopra void ma sotto il margine; NO BET = sotto void.

**Le schedine vengono aggiornate da sole?**  
Sì, tipicamente dopo un aggiornamento globale o un refresh esplicito / “Rigenera schedine” sulla pagina Consiglio schedina.

**Serve capire il machine learning per usarlo?**  
No. Per l’uso quotidiano basta l’interfaccia web e, se vuoi, il bot Telegram.

**Il bot o il sito dicono di riprovare più tardi?**  
È una protezione anti-abuso: troppe richieste in poco tempo. Attendi i secondi indicati e riprova.

---

## Dove approfondire

| Documento | Contenuto |
|-----------|-----------|
| [README.md](../README.md) | Architettura, classi, metodi, API, pipeline ML |
| [SCHEDULING.md](SCHEDULING.md) | Cron / Task Scheduler / sync cloud |
| [BACKUP_DR.md](BACKUP_DR.md) | Backup e ripristino database (operazioni di emergenza, non dalla UI) |
| Swagger UI | Con backend acceso: `http://localhost:8000/docs` |
