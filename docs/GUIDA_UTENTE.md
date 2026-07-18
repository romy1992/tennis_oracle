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
| **Partite** | Elenco partite con pronostico, quote e indicazione di valore (PLAY / NO BET / BORDERLINE) |
| **Consiglio schedina** | Schedine multipla proposte per un giorno, con stake e copia rapida |
| **Statistiche schedine** | Confronto risultati delle schedine tra modelli/versioni |
| **Statistiche previsioni** | Accuratezza e metriche delle previsioni nel tempo |

In alto nella sidebar c’è anche il controllo **Aggiornamento globale**: importa partite, genera previsioni per tutti i modelli disponibili e aggiorna le schedine.

### Come scegliere modello e versione

Nelle pagine puoi scegliere:

- **Versione modello**: `v1`, `v2`, `v3` (default); la scelta resta salvata nel browser
- **Tipo modello**: regressione logistica o random forest

In sintesi:

- **v1 / v2**: il modello **non usa le quote** per predire; le quote servono dopo per edge e value bet
- **v3**: modello **consapevole delle quote** (solo partite con quote disponibili)

La scelta resta salvata nel browser.

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
cp .env.example .env
# oppure configura anche properties/config.env
alembic upgrade head
uvicorn src.app.main:app --reload
```

Variabili importanti in `backend/.env` / `backend/properties/config.env`:

- `DATABASE_URL` — connessione PostgreSQL
- `API_TENNIS_KEY` / `API_TENNIS_BASE` — API tennis
- `CORS_ORIGINS` — origini frontend consentite

API tipica: `http://localhost:8000`  
Health check: `GET http://localhost:8000/health`

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

In `frontend/.env`:

```env
VITE_API_BASE_URL=http://localhost:8000
```

### Bot Telegram (opzionale)

1. Avvia il backend
2. Imposta `TELEGRAM_BOT_TOKEN` e le altre variabili Telegram in `.env`
3. Esegui:

```bash
cd backend
python -m src.app.telegram.bot
```

Comandi tipici: `/start`, `/help`, `/pronostici`, `/giorno`, `/10giorni`, `/schedine`, `/partite`, `/cerca`.

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
Mancano dati storici, odds (per `v3`), o l’aggiornamento non è ancora stato eseguito.

**Cosa significa PLAY / NO BET / BORDERLINE?**  
È il giudizio sul valore della scommessa singola confrontando probabilità del modello e quota di mercato.

**Le schedine vengono aggiornate da sole?**  
Sì, tipicamente dopo un aggiornamento globale o un refresh esplicito della pagina schedine.

**Serve capire il machine learning per usarlo?**  
No. Per l’uso quotidiano basta l’interfaccia web e, se vuoi, il bot Telegram.

---

## Dove approfondire

| Documento | Contenuto |
|-----------|-----------|
| [README.md](../README.md) | Architettura, classi, metodi, API, pipeline ML |
| [SCHEDULING.md](SCHEDULING.md) | Cron / Task Scheduler / sync cloud |
| Swagger UI | Con backend acceso: `http://localhost:8000/docs` |
