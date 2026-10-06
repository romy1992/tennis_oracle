# Prova schedine — consegna per la sessione successiva

Questo file è il punto da leggere prima di toccare consiglio, soglie o modello.
La pagina è **Prova schedine** (`/slip-shape-trial`), menu Backtest / Ops.
Il codice è `backend/src/app/services/slip_shape_trial.py`.
Consiglio schedina non va modificato da questo lavoro.

## Cosa è già stato deciso

Periodo di scelta, congelato: **7 agosto 2026 – 5 ottobre 2026**.
Modello: **v4 / voting_ensemble**. Stake simulato: **10**.
Split del controllo: **1 settembre 2026**. Minimo per far passare una regola: **30 casi per metà**, ROI positivo su entrambe.

Risultato di quel controllo, riletto sul database dell'app:

- Le Generiche chiudono a circa **−12%** di ROI (hit dei pick circa 64%).
- Il modello azzecca il vincitore intorno al **70%** e non va riaddestrato come primo passo.
- L'edge e l'etichetta PLAY non sono un segnale di valore. Più l'edge è alto, peggio è andata nel periodo congelato.
- L'unica regola che resta positiva sia ad agosto sia a settembre è la quota match winner **1,50–1,80** (agosto circa +2% su 34 partite, settembre circa +19% su 30).
- La forma corta con quella fascia, sullo stesso periodo, è circa **19 vinte / 15 perse, ROI +17%** su 34 schedine. È un replay delle giornate che hanno scelto la fascia, non una conferma.

## Come si esegue il test successivo

La regola resta **quota 1,50–1,80**, match winner, al massimo due pick al giorno, i più probabili.
Over/under e primo set restano fuori dalla multipla.
I giorni contati partono dal **6 ottobre 2026** compreso. Non si rimescolano con agosto e settembre e non si cerca un'altra fascia.

Esecuzione, senza scrivere schedine nuove:

1. Aprire **Prova schedine**, oppure `GET /api/slip-shape-trial` da admin.
2. Leggere il blocco **Prova dal 6 ottobre** (`forward` nella risposta).
3. Se `forward.ready` è falso, fermarsi. Il numero da raggiungere è **30 schedine corte chiuse**.
4. Se `forward.ready` è vero, leggere solo il ROI di quel blocco. Poi se ne parla prima di cambiare il consiglio.

Nel periodo congelato usciva circa una schedina corta ogni due giorni. Trenta chiuse, a quel ritmo, arrivano **verso la fine di novembre 2026**. Una lettura prima di allora non decide nulla.

## Cosa non fare prima di quelle 30

- Non cambiare soglie, profili o la pagina Consiglio.
- Non riaddestrare v4.
- Non promuovere la fascia 1,50–1,80 perché agosto è solo a +2%.
- Non ricalcolare le fasce aggiungendo i giorni nuovi al periodo congelato: quelli servono a controllare la regola, non a risceglierla.
