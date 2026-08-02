# M48 — Gen4 Historical Evidence Acquisition V3

## Obiettivo

Recuperare storico Solana sufficiente per rieseguire M47 e ottenere un primo confronto tra:

- `STRICT_GEN4`;
- `SIGNAL_ONLY_PROXY`;
- `SIMPLE_COPY_BASELINE`.

M48 non attiva M31, paper trading, LIVE, worker, scheduler, signer o submit.

## Correzione V3

Il wallet prioritario può essere fornito esplicitamente anche quando non esiste in `discovered_wallets`.
In quel caso viene trattato esclusivamente come target esterno di ricerca:

- selezione `EXPLICIT_EXTERNAL_EVIDENCE_ONLY`;
- nessuna creazione automatica di una riga in `discovered_wallets`;
- nessun punteggio, ranking, classificazione qualità o promozione assegnati;
- nessun uso come source wallet operativo;
- nessun accesso a M31, paper o LIVE;
- `force=False` obbligatorio;
- storico e metadati di backfill salvati nelle tabelle già esistenti.

Un wallet già registrato come `SOSPETTO` resta sempre rifiutato. L'auto-selezione continua a usare solo wallet presenti nel database.

## Sicurezza

- massimo 5 wallet;
- massimo 20 richieste Helius per wallet;
- massimo 50 richieste Helius complessive;
- comando iniziale consigliato: 2 wallet × 10 richieste = massimo 20;
- paginazione riprendibile tramite cursore;
- deduplicazione per firma;
- nessuna chiave stampata;
- nessuna richiesta esterna durante la preview;
- nessun ricalcolo qualità durante `evidence_only`;
- nessuna promozione o modifica dei gate;
- nessuna transazione costruita, firmata o inviata.

## Interpretazione del risultato

Lo storico retroattivo può alimentare il proxy e la baseline. Non può ricreare retroattivamente snapshot e decisioni point-in-time che non esistevano al momento del segnale. Per questo un verdetto strict richiederà comunque evidenza forward senza look-ahead.

## Head Alembic

M48 non aggiunge migrazioni. Head repository e database restano:

`e3b5c8d1f297`
