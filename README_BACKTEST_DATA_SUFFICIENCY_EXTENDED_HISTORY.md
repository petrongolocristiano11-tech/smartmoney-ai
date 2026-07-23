# SmartMoney AI — Backtest Data Sufficiency & Extended Candidate History

Data blocco: 23 luglio 2026

## Obiettivo

Questo blocco impedisce che un candidato venga promosso o bocciato definitivamente quando il backtest usa un campione troppo corto o incompleto.

Il flusso diventa:

`Discovery → Hydration → Activity → Quality → Extended History → Data Sufficiency → Backtest → Promotion Gate`

Un wallet può risultare idoneo finale soltanto quando:

1. è `ATTIVO`;
2. è `COPIABILE`;
3. supera lo Smart Score minimo;
4. dispone di dati storici sufficienti;
5. ottiene `PROMOSSO` dal backtest;
6. supera il controllo di compatibilità Jupiter.

## Storico esteso controllato

Il backfill storico è manuale ed è consentito, per impostazione predefinita, soltanto ai wallet classificati `COPIABILE`.

Caratteristiche:

- storico configurabile da 7 a 90 giorni;
- massimo 20 richieste Helius per esecuzione;
- massimo 100 transazioni per pagina;
- paginazione tramite firma `before-signature`;
- filtro esclusivo sulle transazioni `SWAP`;
- intervallo temporale limitato con `gte-time` e `lte-time`;
- una sola richiesta per pagina;
- retry automatici disabilitati nel batch;
- deduplica delle firme tra pagine e con i trade già presenti;
- salvataggio e commit di ogni pagina completata;
- conservazione delle pagine già importate se una richiesta successiva fallisce;
- ricalcolo finale di Smart Score, attività, qualità, ranking e idoneità.

Stati possibili:

- `COMPLETED`: storico completato entro la finestra richiesta;
- `PARTIAL`: budget terminato, parse parziali o errore dopo almeno una pagina valida;
- `EMPTY`: nessuna transazione trovata;
- `FAILED`: nessuna pagina importata a causa di un errore.

Motivi di arresto:

- `LOOKBACK_REACHED`;
- `LAST_PAGE`;
- `EMPTY_PAGE`;
- `REQUEST_BUDGET_EXHAUSTED`;
- `CURSOR_REPEATED`;
- `CURSOR_MISSING`;
- `FAILED`.

Le pagine corte non vengono considerate automaticamente come fine dello storico: il batch prosegue fino a pagina vuota, raggiungimento della finestra, cursore non valido o budget esaurito. Le risposte Helius che richiedono una firma di continuazione vengono seguite entro lo stesso budget rigido.

## Ricostruzione delle posizioni precedenti

Il nuovo backtest divide i dati in due periodi:

- **warmup**, predefinito a 14 giorni;
- **analisi**, predefinita a 30 giorni.

Il warmup ricostruisce le posizioni aperte prima dell'inizio della finestra di analisi. Le posizioni ancora aperte al termine del warmup vengono riportate nel backtest come posizioni `bootstrap`.

Il loro valore viene ribasato al momento iniziale dell'analisi, così il PnL del warmup non altera il rendimento misurato nel periodo principale.

## Cache Jupiter per token

La compatibilità round-trip `SOL → token → SOL` viene memorizzata in base a:

- token mint;
- size fissa in lamport;
- slippage configurato.

La cache scade dopo 6 ore per impostazione predefinita, con intervallo configurabile da 1 a 24 ore. Un backtest successivo può riutilizzare un risultato valido senza nuove richieste Jupiter oppure forzare esplicitamente il refresh.

Per ogni backtest vengono salvati:

- richieste Jupiter effettive;
- cache hit;
- token controllati dal vivo;
- esito e scadenza per ciascun token.

La cache contiene soltanto quote e metadati: non contiene transazioni firmate e non invia ordini.

## Data Sufficiency Gate

Prima di valutare la performance, il sistema richiede contemporaneamente:

- almeno 5 posizioni chiuse;
- almeno 5 giorni di storico effettivo;
- almeno 10 trade sorgente nella finestra di analisi;
- copertura di esecuzione almeno del 40%;
- almeno il 50% dei segnali SELL associati a una posizione;
- rapporto posizioni ancora aperte non superiore al 50%.

Il sistema calcola:

- `data_sufficient`;
- `data_sufficiency_score`;
- motivazioni di insufficienza;
- giorni effettivi coperti;
- trade di warmup e di analisi;
- posizioni bootstrap create e chiuse;
- rapporto SELL associati;
- rapporto posizioni aperte.

## Decisioni

### DATI_INSUFFICIENTI

Ha precedenza sulla valutazione economica quando il wallet supera Activity, Quality e Smart Score ma non raggiunge tutte le soglie minime del campione.

Un rendimento negativo con pochi cicli completi non produce più una bocciatura definitiva.

### PROMOSSO

Richiede dati sufficienti e contemporaneamente:

- rendimento netto positivo;
- win rate almeno 40%;
- profit factor almeno 1,10;
- drawdown massimo non superiore al 25%;
- massimo 2 posizioni aperte alla fine;
- compatibilità Jupiter almeno 80%.

### OSSERVAZIONE

I dati sono sufficienti, ma mancano una o più condizioni di promozione senza condizioni gravi di bocciatura; oppure Activity, Quality o Smart Score non superano i prerequisiti.

### BOCCIATO

È possibile soltanto con dati sufficienti e condizioni gravi, come perdita almeno del 5%, drawdown superiore al 40%, profit factor inferiore a 0,80 o compatibilità Jupiter nulla.

## Endpoint

- `POST /discovered-wallets/promotion/history/backfill`
- `GET /discovered-wallets/promotion/history/{wallet_address}/latest`
- `POST /discovered-wallets/promotion/backtest`
- `GET /discovered-wallets/promotion/{wallet_address}/latest`

## Migrazione Alembic

Nuova revisione:

```text
f6a8d3c1e927
```

Revisione precedente:

```text
e4b7c2a9d815
```

La migrazione:

- crea `candidate_history_backfill_runs`;
- crea `candidate_token_compatibilities` per la cache Jupiter;
- aggiunge i campi dello storico esteso ai wallet scoperti;
- aggiunge le metriche di sufficienza ai backtest;
- aggiunge il gate di sufficienza al ranking operativo;
- disabilita tutte le vecchie idoneità in modalità fail-closed;
- riclassifica temporaneamente i wallet `COPIABILE` come `DATI_INSUFFICIENTI`;
- non modifica ordini, posizioni o generazioni DRY_RUN.

## Prima esecuzione consigliata

Per `EXmyra6cugUEDnUjUcyk6KGhesRLc8312ZvSSDNCBJxy`:

### 1. Storico esteso

- giorni: 30;
- budget Helius: 5;
- transazioni per pagina: 100.

### 2. Backtest

- analisi: 30 giorni;
- warmup: 14 giorni;
- capitale iniziale: 1 SOL;
- size BUY: 0,05 SOL;
- slippage: 100 bps;
- commissioni: 10 bps;
- ritardo: 8 secondi;
- massimo 5 posizioni aperte;
- controllo Jupiter: attivo.

Se lo storico termina con `REQUEST_BUDGET_EXHAUSTED`, il risultato è parziale ma i dati importati restano salvati. Non ripetere automaticamente il batch: controllare prima data più vecchia, pagine e richieste usate.

## Railway

Dopo commit e push:

1. verificare backend `Success`;
2. verificare migrazione fino a `f6a8d3c1e927`;
3. verificare frontend `Success`;
4. aprire Discovery;
5. selezionare il candidato;
6. eseguire una sola volta `Estendi storico` con 30 giorni e budget 5;
7. eseguire il backtest solo dopo il completamento del backfill;
8. leggere sufficienza, decisione e motivazioni;
9. non applicare ancora wallet e non creare una nuova generazione.

## Invarianti di sicurezza

Questo blocco non:

- abilita o arma LIVE;
- abilita lo stream automatico;
- avvia il worker;
- crea sottoscrizioni Helius;
- esegue retry automatici nel backfill;
- usa Helius durante il backtest;
- firma o invia transazioni Jupiter;
- applica wallet al worker;
- resetta la Generazione #3;
- crea la Generazione #4.
