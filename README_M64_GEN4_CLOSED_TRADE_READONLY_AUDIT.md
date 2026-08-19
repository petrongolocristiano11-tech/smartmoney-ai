# M64 — Audit Gen4 read-only 83 + round trip ricostruibili

## Scopo

M64 costruisce un audit separato dalla prova real-time ufficiale della campagna
`e5eaf7b6-a4e7-4182-96a2-d5f6af668e74` e del wallet congelato
`Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd`.

Il contatore production resta 83. Le ricevute `RECOVERY_ONLY` e i round trip
pubblici ricostruiti non vengono mai trasformati in evidenza webhook real-time.

## Contratto di sicurezza

- database PostgreSQL aperto in transazione `REPEATABLE READ READ ONLY`;
- verifica obbligatoria di `current_database() = smartmoney_gen4`;
- verifica obbligatoria di `transaction_read_only = on`;
- Alembic head attesa `c8a1f3d6e942`;
- contatore ufficiale obbligatorio 83, `RECOVERY_ONLY` obbligatorio 28 e zero
  posizioni copyability ufficiali aperte prima della ricostruzione;
- PnL ufficiale dei 83 obbligatorio `32.319.569` lamport e coerente con le
  metriche Gen4 persistite;
- candidata unica campagna `ACTIVE`, primaria M63 ancora `PAUSED` e vecchio
  forward feed `d11626bf-e9ba-4305-b3a9-5c6386148e72` ancora disabilitato;
- zero richieste Helius; ogni hostname contenente `helius` viene rifiutato;
- solo RPC pubblico Solana finalizzato, con throttle 0,60 secondi, `Retry-After`,
  backoff e massimo 8 tentativi;
- zero backend POST, zero DB write/commit, zero Jupiter storico;
- zero paper/LIVE, signer, firma o submission;
- output obbligatoriamente fuori dal repository Git.

## Ricostruzione

Il runner legge atomically i 83 trade ufficiali e la `policy_snapshot`. Poi
recupera tutte le firme pubbliche dopo il confine M63 congelato, fino al confine
stesso, e scarica le transazioni `jsonParsed` finalizzate.

Ogni transazione viene classificata dal parser M62 reale
`canonical-parser-gen4-raw-balance-delta/4`. Gli eventi validi sono elaborati in
ordine cronologico, senza look-ahead. La simulazione replica:

- le due entrate real-time esatte che risultano già quotate nel database ma la
  cui uscita successiva è stata quarantinata come `RECOVERY_GAP_QUARANTINE`;
- input fisso della campagna per ogni BUY;
- slippage bps congelato;
- fee di rete stimata congelata per entrata e uscita;
- SELL fraction del wallet sorgente;
- allocazione pro-rata sulle posizioni aperte;
- chiusura su full exit o dust Gen4 dello 0,1%;
- firme complete, hash SHA-256 delle transazioni ed equity curve.

Il prezzo proxy non è un rapporto tra soli token balance: usa il delta del token
del wallet e il delta SOL/WSOL della stessa transazione, al netto/lordo della fee
on-chain secondo il lato BUY/SELL. Non usa prezzi futuri.

Se esistono più di 17 chiusure, il report seleziona le prime 17 con lo stesso
ordinamento production `(closed_at, id)` usato dal calcolo Gen4. Se il confine
taglia un'unica transazione che chiude più posizioni, il report conserva anche
una sensitivity separata sul batch completo: non sposta il target 83+17 e non
nasconde le posizioni supplementari. Se esistono meno di 17 chiusure, dichiara
il numero reale e non forza il campione.

## Qualità dell'evidenza

| Blocco | Qualità |
| --- | --- |
| 83 ufficiali | esatto, letto read-only dalle posizioni Gen4 production |
| firme/transazioni | osservato dal ledger pubblico finalizzato |
| pairing BUY/SELL | deterministico Gen4, senza look-ahead |
| capitale/fee/slippage | parametri esatti della policy applicati al proxy |
| prezzi ricostruiti | stima conservativa dalla stessa transazione on-chain |
| quote e build Jupiter storiche | non disponibili, non inventate |
| latenza/price impact/PRICE_ALREADY_MOVED storici | non disponibili |
| campione 83+N | equivalente analitico, mai prova real-time ufficiale |

Per quantificare l'impatto dei costi, ogni trade ricostruito viene rigiocato in
quattro scenari: policy netta, senza slippage, senza fee e senza entrambi. Il
report separa impatto fee, slippage, totale e interazione di arrotondamento.

## Metriche prodotte

Per 83 ufficiali, N ricostruiti e 83+N vengono calcolati separatamente:

- PnL netto in lamport e SOL;
- rendimento netto percentuale;
- gross profit e gross loss;
- profit factor e win rate;
- max drawdown in lamport, SOL e percentuale con metodo Gen4;
- migliore/peggiore trade;
- media e mediana PnL/return;
- equity curve;
- fee e impatto costi;
- sensitivity del batch di chiusura completo al confine del 100º trade;
- reject rate osservato ufficiale, parser reject rate e limiti del reject rate
  combinato quando l'ammissione Jupiter storica è ignota.

## Output

`RUN_M64_GEN4_CLOSED_TRADE_READONLY_AUDIT.ps1` crea nella cartella
`Downloads\smartmoney-audits`:

1. `smartmoney-m64-public-raw-evidence-<UTC>.json` con transazioni pubbliche,
   firme complete e hash;
2. `smartmoney-m64-83-plus-17-readonly-audit-<UTC>.json` con i tre campioni,
   metriche, qualità, limiti e verdict.

Il wrapper valida marker reali, incluso:

```text
OFFICIAL_REALTIME_TRADES=83
RECONSTRUCTED_CLOSED_TRADES=N
COMBINED_EQUIVALENT_SAMPLE=83+N
HELIUS_REQUESTS=0
DATABASE_WRITES=0
BACKEND_POSTS=0
```

## Installazione, test e rollback

L'installer del pacchetto richiede branch `main`, HEAD
`fe63c528e55af84a97d6deb6872e825a5a43c6b4` e worktree pulita. Verifica il
manifest SHA-256, crea un backup esterno, copia file completi, esegue compileall,
verifier M58–M64, test mirati M58–M64, Alembic heads, suite completa e
`git diff --check`. In caso di errore ripristina automaticamente il backup.

Non esegue commit, push, deploy, Alembic upgrade/downgrade, Railway mutation o
scritture production. M64 non aggiunge una migrazione: l'head resta invariata.

Il rollback confronta gli hash installati prima di rimuovere/ripristinare file,
così non sovrascrive modifiche successive senza un'esplicita forzatura.
