# SmartMoney AI — Wallet Quality & Execution Suitability

Data blocco: 2026-07-23

## Obiettivo

Questo blocco aggiunge un controllo qualitativo obbligatorio dopo Activity Discovery e Controlled Hydration. Un wallet non è più idoneo solo perché ha Smart Score alto e attività recente: deve dimostrare che le operazioni salvate sono realmente copiabili con la strategia DRY_RUN e con size target di 0,05 SOL.

## Classificazioni

- `COPIABILE`: attività recente, campione sufficiente, size reali, BUY e SELL, concentrazione accettabile e almeno un ciclo BUY→SELL.
- `OSSERVAZIONE`: dati non sospetti ma campione, attività, diversità o compatibilità ancora insufficienti.
- `SOSPETTO`: dust/spam, pattern solo BUY o solo SELL, volume non coerente o concentrazione estrema.
- `NON_COPIABILE`: wallet inattivo o iperattivo.
- `NON_ANALIZZATO`: qualità non ancora ricalcolata.

Solo `COPIABILE` può avere `quality_eligible=true`. L'idoneità finale richiede contemporaneamente:

1. Smart Score minimo;
2. Activity idonea;
3. Quality `COPIABILE`.

## Metriche persistenti

- swap analizzati negli ultimi 7 giorni;
- swap significativi;
- swap dust e percentuale dust;
- importo medio e mediano in SOL;
- compatibilità con size target 0,05 SOL;
- equilibrio BUY/SELL;
- token unici;
- concentrazione sul token principale;
- token con ciclo BUY→SELL completo;
- percentuale di token con round trip;
- importi nulli o non validi;
- Quality Score, classificazione, motivazioni e data di calcolo.

## Integrazioni

- Discovery e Smart Discovery salvano anche la qualità.
- Hydration ricalcola qualità e idoneità subito dopo l'import.
- `Ricalcola attività DB` aggiorna attività, qualità e ranking.
- Il nuovo endpoint `POST /discovered-wallets/quality/refresh` usa solo il database e restituisce il riepilogo delle classi.
- Il ranking LIVE eredita Quality Score e classificazione e non può rendere idoneo un wallet non `COPIABILE`.
- La migrazione azzera in modo fail-closed le vecchie idoneità finché non viene effettuato il nuovo ricalcolo.

## Soglie principali

- dust: importo fino a `0,001 SOL`;
- swap significativo: almeno `0,005 SOL`;
- compatibilità size: tra `0,02` e `5 SOL`;
- dust massimo per `COPIABILE`: 25%;
- compatibilità size minima: 50%;
- equilibrio BUY/SELL minimo: 20%;
- almeno 2 token unici;
- concentrazione massima sul token principale: 85%;
- almeno un ciclo BUY→SELL;
- almeno 2 giorni attivi;
- Smart Score minimo: 60.

Le soglie sono costanti esplicite e testate in `wallet_quality_service.py`.

## Migrazione

- revisione precedente: `b7d4e8f1c902`;
- nuova revisione: `c9e4a7f2d631`;
- unica head prevista: `c9e4a7f2d631`.

Il comando Railway già previsto resta:

```bash
alembic upgrade head
```

## Operazione sicura dopo il deploy

Nella pagina Discovery premere soltanto:

1. `Ricalcola qualità DB`;
2. `Aggiorna elenco`.

Il ricalcolo usa zero richieste Helius. Non premere `Applica wallet idonei` e non creare la Generazione #4.

## Sicurezza invariata

- LIVE non abilitato e non armato;
- stream automatico non avviato;
- worker non avviato;
- nessuna sottoscrizione Helius;
- Generazione #3 non modificata o resettata;
- Generazione #4 non creata;
- nessun wallet applicato automaticamente;
- Telegram e Discord non implementati.
