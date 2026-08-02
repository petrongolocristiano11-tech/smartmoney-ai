# M51 — Gen4 Price Integrity

M51 corregge il replay economico Gen4 senza modificare dati, migrazioni, gate di qualità o stato operativo.

## Difetti corretti

1. SOL, native SOL sentinel, USDC e USDT non possono più diventare token speculativi nei segnali o nella baseline.
2. La lista dei mint esclusi è centralizzata e può essere estesa tramite configurazione.
3. I punti prezzo con discontinuità superiore al rapporto configurato nella finestra temporale locale vengono scartati.
4. Take-profit e stop-loss vengono contabilizzati al prezzo soglia, con frizione di uscita, invece che al prezzo estremo del punto successivo.
5. Un punto incompatibile con l'entrata non può generare un rendimento estremo; viene ignorato e l'operazione resta non risolta se non esiste un'uscita valida.

## Configurazione

- `CANONICAL_PARSER_GEN4_PROFITABILITY_EXCLUDED_TOKEN_MINTS`
- `CANONICAL_PARSER_GEN4_PROFITABILITY_PRICE_CONTINUITY_WINDOW_SECONDS=3600`
- `CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PRICE_DISCONTINUITY_RATIO=25.0`

I mint obbligatori SOL/USDC/USDT non possono essere rimossi tramite configurazione; la variabile aggiunge soltanto esclusioni ulteriori.

## Sicurezza

- nessuna migrazione Alembic;
- database invariato a `e3b5c8d1f297`;
- nessuna richiesta Helius o Jupiter;
- nessuna scrittura M47 durante la preview;
- nessuna promozione wallet;
- nessun paper order;
- nessuna firma o transazione;
- LIVE non attivato.

## Verifica

L'installer esegue test mirati, suite completa, verifier OpenAPI, controllo del database e ricalcolo M47 read-only sugli stessi dati già importati.
