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

Nel menu laterale trovi:

| Voce | A cosa serve |
|------|----------------|
| **Partite** | Elenco partite con pronostico, quota void e stato valore (PLAY / BORDERLINE / NO BET) e stato partita (da giocare, rinviata, annullata, …) |
| **Consiglio schedina** | Fino a 9 schedine per giorno a difficoltà crescente: 3 solo Play, 3 Play+Borderline, 3 miste |
| **Statistiche schedine** | Confronto risultati delle schedine tra modelli/versioni |
| **Statistiche previsioni** | Accuratezza e metriche delle previsioni nel tempo |
| **Report aggiornamento** | Esito dell’ultima run “Aggiorna tutto”: errori, warning, fasi e combo modello |
| **Bot Telegram** | Solo admin: accessi e comandi usati sul bot (KPI, filtri per data/utente/comando, breakdown giornaliero, storico) |

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

### Stato partita e schedine ridotte

Nella colonna **Stato** (Partite) e nei dettagli pick (Schedine) vedi anche se la partita è rinviata, annullata, abbandonata, walkover, ecc.

Regole sulle schedine:

- pick di una partita **non disputata in modo definitivo** → **Annullato** (escluso dalla quota)
- se restano solo pick presi + eventuali annullati → schedina **Presa**, con **quota effettiva** senza le gambe annullate
- rinvio (ancora da giocare) → pick **In corso**, schedina resta in corso
- se **tutti** i pick sono annullati → schedina **Annullata** (puntata restituita / profitto 0)
- walkover / ritiro **con vincitore** → conteggiati come presa/persa normalmente

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

- Python 3.12+ consigliato
- Node.js (per il frontend)
- PostgreSQL con database `tennis_db`
- Chiave API tennis (`API_TENNIS_KEY`)

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env .env
# oppure configura anche properties/config.env
alembic upgrade head
uvicorn src.app.main:app --reload
```

Variabili importanti in `backend/.env` / `backend/properties/config.env`:

- `DATABASE_URL` — connessione PostgreSQL
- `API_TENNIS_KEY` / `API_TENNIS_BASE` — API tennis
- `API_TENNIS_TIMEOUT` — timeout HTTP verso API tennis in secondi (opzionale, default 30)
- `CORS_ORIGINS` — origini frontend consentite
- `TELEGRAM_BOT_TOKEN` — solo se usi il bot (opzionale)

API tipica: `http://localhost:8000`  
Health check: `GET http://localhost:8000/health`

### Frontend

```bash
cd frontend
npm install
cp .env .env
npm run dev
```

In `frontend/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

### Bot Telegram (opzionale)

1. Avvia il backend (`alembic upgrade head` serve anche per la tabella analytics `telegram_bot_event`)
2. Imposta in `backend/.env` almeno `TELEGRAM_BOT_TOKEN` (e opzionalmente `TELEGRAM_API_BASE_URL`, versione/modello, margine, ecc.)
3. Esegui:

```bash
cd backend
python -m src.app.telegram.bot
```

Comandi attivi: `/start`, `/help`, `/schedine`, `/partite`, `/statistiche`.

Con `/schedine` ricevi le stesse schedine della pagina **Consiglio schedina** (fino a 9, con Void/Edge/ROI/Valore e stato pick). Se i due motori del giorno producono schedine diverse, il bot le mostra entrambe etichettate con l’accuratezza storica (senza nomi tecnici); se sono uguali ne manda una sola. Il primo messaggio indica solo la data e la legenda degli esiti: verde = Presa, rosso = Persa, grigio = In corso, grigio scuro = Annullata.

Con `/partite` ricevi le partite di oggi come in pagina **Partite** (Predetto, Conf., Void, Valore, Stato). Anche qui, se i motori danno pronostici diversi li vedi entrambi con etichetta accuratezza; l’intro è solo data + legenda stati.

Con `/statistiche` vedi un riepilogo immagine dell’andamento (partite singole e schedine, con profitto sulle schedine), sempre senza nomi modello.

Nella dashboard web, la voce **Bot Telegram** mostra a te (admin) chi ha usato il bot e quali comandi (filtri per periodo, utente, azione): non è visibile agli utenti Telegram.

---

## Flusso quotidiano consigliato

1. Avvia backend e frontend
2. Esegui un **aggiornamento globale** (dalla UI) oppure il job giornaliero (vedi [SCHEDULING.md](SCHEDULING.md))
3. Apri **Partite** per i pronostici del giorno
4. Apri **Consiglio schedina** se vuoi una proposta multipla
5. Controlla le **statistiche** per capire come stanno performando i modelli

Se usi un database cloud separato, il job giornaliero può anche **sincronizzare** i dati dal PC locale al cloud (configurazione in `properties/config.env`).

---

## Domande frequenti

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

---

## Dove approfondire

| Documento | Contenuto |
|-----------|-----------|
| [README.md](../README.md) | Architettura, classi, metodi, API, pipeline ML |
| [SCHEDULING.md](SCHEDULING.md) | Cron / Task Scheduler / sync cloud |
| Swagger UI | Con backend acceso: `http://localhost:8000/docs` |
