# SmartMoney AI — Historical Candidate Backtest & Promotion Gate

Data blocco: 23 luglio 2026

## Obiettivo

Questo blocco aggiunge l'ultimo gate obbligatorio prima che un wallet scoperto possa risultare idoneo al copy trading. Un wallet deve già essere `ATTIVO` e `COPIABILE`, quindi deve superare un backtest storico conservativo e la verifica di quotabilità Jupiter.

Il gate è **fail-closed**: dopo la migrazione nessun wallet è idoneo finale finché non ottiene lo stato `PROMOSSO`.

## Cosa simula

Il motore usa soltanto gli swap già salvati nel database e simula:

- capitale iniziale configurabile;
- size BUY fissa, predefinita a `0,05 SOL`;
- una sola posizione aperta per token;
- numero massimo di posizioni contemporanee;
- slippage in basis point;
- commissioni in basis point;
- penalità prudenziale legata al ritardo di copy trading;
- BUY duplicati, SELL senza posizione, capitale insufficiente e segnali non eseguibili;
- valorizzazione delle posizioni ancora aperte all'ultimo prezzo storico disponibile.

## Metriche calcolate

- trade storici analizzati;
- segnali BUY e SELL;
- BUY eseguiti;
- posizioni chiuse e ancora aperte;
- copertura di esecuzione;
- capitale finale;
- PnL realizzato, non realizzato e netto;
- rendimento percentuale;
- win rate;
- profit factor;
- massimo drawdown;
- score del backtest;
- compatibilità Jupiter corrente.

## Verifica Jupiter

Quando attiva, la verifica richiede esclusivamente quote round-trip:

1. `SOL → token`;
2. `token → SOL` usando l'output della prima quota.

Non viene fornito un wallet `taker`, non viene firmata alcuna transazione e non viene chiamato l'endpoint di esecuzione. Il numero massimo di token controllati è configurabile e limitato.

## Decisioni

### PROMOSSO

Richiede contemporaneamente:

- attività `ATTIVO`;
- qualità `COPIABILE`;
- Smart Score almeno 60;
- almeno 3 posizioni chiuse;
- rendimento netto positivo;
- win rate almeno 40%;
- profit factor almeno 1,10;
- drawdown massimo non superiore al 25%;
- copertura di esecuzione almeno 50%;
- non più di 2 posizioni aperte alla fine;
- verifica Jupiter superata con compatibilità almeno 80%.

### OSSERVAZIONE

Il wallet non presenta condizioni di bocciatura grave, ma non soddisfa ancora tutti i requisiti di promozione. Le motivazioni vengono salvate e mostrate nell'API e nel frontend.

### BOCCIATO

Scatta in presenza di almeno una condizione grave, per esempio:

- nessuna posizione completa;
- rendimento uguale o inferiore a -5%;
- drawdown superiore al 40%;
- profit factor inferiore a 0,80;
- compatibilità Jupiter pari a zero dopo una verifica eseguita.

## Idoneità finale

L'idoneità finale ora richiede:

`Activity Gate + Quality Gate + Promotion Gate + Smart Score`

Un wallet `COPIABILE` ma non ancora analizzato non è idoneo. Anche il ranking operativo LIVE applica lo stesso filtro, senza applicare automaticamente alcun wallet.

## Nuovi endpoint

- `POST /discovered-wallets/promotion/backtest`
- `GET /discovered-wallets/promotion/{wallet_address}/latest`

L'elenco `/discovered-wallets` supporta anche filtro `promotion_status` e ordinamento per metriche del backtest.

## Migrazione Alembic

Nuova revisione:

```text
e4b7c2a9d815
```

Revisione precedente:

```text
c9e4a7f2d631
```

La migrazione:

- aggiunge i campi riassuntivi del gate ai wallet scoperti;
- aggiunge i campi riassuntivi al ranking operativo;
- crea la tabella `candidate_backtest_runs`;
- disabilita in modo fail-closed le vecchie idoneità fino al nuovo backtest;
- non modifica tabelle, ordini o posizioni DRY_RUN.

## Parametri iniziali consigliati

Per il primo candidato `EXmyra6cu...DNCBJxy`:

- storico: 7 giorni;
- capitale iniziale: 1 SOL;
- size BUY: 0,05 SOL;
- slippage: 100 bps;
- commissioni: 10 bps;
- ritardo: 8 secondi;
- massimo 5 posizioni aperte;
- controllo Jupiter: attivo;
- massimo 10 token controllati.

## Invarianti di sicurezza

Questo blocco non:

- abilita o arma LIVE;
- abilita lo stream automatico;
- avvia il worker;
- crea sottoscrizioni Helius;
- usa richieste Helius durante il backtest;
- firma o invia transazioni Jupiter;
- applica wallet al worker;
- resetta la Generazione #3;
- crea la Generazione #4.

## Procedura Railway

Dopo test locale, commit e push:

1. verificare deploy backend `Success`;
2. verificare migrazione fino a `e4b7c2a9d815`;
3. verificare deploy frontend `Success`;
4. aprire Discovery;
5. selezionare il wallet candidato;
6. eseguire un solo backtest con i parametri iniziali;
7. leggere decisione, metriche e motivazioni;
8. non premere ancora `Applica wallet idonei` anche in caso di promozione.
