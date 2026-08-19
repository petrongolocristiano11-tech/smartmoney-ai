# M73 — Controlled New Wallet Acquisition & Qualification

M73 esegue il passo deciso da M72 senza riattivare la vecchia discovery automatica.

## Fase A — acquisizione Helius rigidamente limitata

M73 riusa **esattamente** la corsia M66 già installata e verificata (hash bloccati), senza riscriverla. L'esecuzione reale richiede la conferma esplicita:

`EXECUTE_M73_CONTROLLED_ACQUISITION_MAX_600_HELIUS_CREDITS`

La corsia M66 mantiene i vincoli già certificati: massimo 6 richieste Enhanced, massimo 600 crediti stimati, zero retry, cache firmata, Enhanced automatico disabilitato. Il seed viene scelto deterministicamente tra i wallet M72 `OBSERVE_ONLY` (priorità al maggior numero di trade chiusi) oppure può essere passato esplicitamente.

## Fase B — qualifica Gen4 Zero-Helius

I nuovi indirizzi vengono deduplicati contro tutti i wallet già ruotati/bloccati da M72. Solo i migliori 3 candidati del pre-screen vengono analizzati in profondità. La prova economica non usa i dati Enhanced a singola pagina: usa il parser canonico Gen4 su RPC Solana pubblico, cache SHA-256, massimo 500 firme per candidato e cap hard complessivo di 1800 tentativi RPC.

Un candidato può diventare `QUALIFIED_PENDING_SHORT_CANARY` soltanto se lo storico è completo e il gate economico Gen4 già usato da M67-M71 passa integralmente. Storico incompleto => `OBSERVE_ONLY / NEEDS_MORE_PUBLIC_RPC_HISTORY`; campione completo >=100 che fallisce il gate => `RESEARCH_ONLY`; profilo sell-only o parser yield definitivamente insufficiente => `REJECTED_FROM_PROMOTION`.

## Cosa M73 NON fa

- non applica wallet a worker/campagne;
- non avvia la short canary;
- non autorizza Micro Live;
- non abilita signer;
- non crea paper/live order;
- non usa Jupiter;
- non modifica il contatore Strict Forward ufficiale (83);
- non riattiva cron, campagna primaria o vecchio forward feed;
- non esegue commit, push o deploy;
- non richiede migrazioni Alembic.

## Output

In `Downloads\smartmoney-audits` salva un report M73 firmato e la cache RPC aggiornata. Se emerge almeno un qualificato, il prossimo step è M74 Short Real-Time Canary Preparation; altrimenti il report indica se continuare la rotazione controllata o lo storico pubblico.


## M73 HOTFIX2 — DATABASE_PUBLIC_URL pre-network + lock recovery scoped

Hotfix2 parte dalla baseline M73 Hotfix1 già installata. Il wrapper riusa il pattern
M67-M70: se `DATABASE_PUBLIC_URL` non è già presente, avvia il runner M73 con
`railway.cmd run --service Postgres --environment production --no-local` usando
esplicitamente il Python della `.venv`. Nessun fallback a `DATABASE_URL`.

Il runner verifica `DATABASE_PUBLIC_URL` prima di creare o recuperare il lock e
prima di invocare la corsia M66. Il recovery del lock è consentito solo con la
conferma esplicita `RECOVER_M73_PRENETWORK_DATABASE_PUBLIC_URL_FAILURE_HOTFIX2`,
solo sul piano M72 SHA-256 `328abe2296e8b91700756376175337d24cffd598c3cf12e9bb49872c69405bd8`,
solo se il lock è ancora l'esatto `STARTED` originale 6/600/0 e non esistono
output M66/M73 creati dopo quel lock. Non esiste re-arm generico.


### Hotfix2 preflight ambiente M66 prima del lock

Dopo aver acquisito una `DATABASE_PUBLIC_URL` valida dal contesto Postgres, M73
esegue **prima del lock one-shot** un probe read-only del vero ambiente che M66
usera: `railway run --service smartmoney-ai --environment production --no-local`.
Il probe accetta solo due marker booleani: database pubblico valido e
`HELIUS_API_KEY` presente. Nessun URL, password o API key viene stampato. Se il
probe non passa, M73 termina senza creare/recuperare il lock e senza richieste
Helius. In questo modo il recovery del fallimento osservato non viene consumato
prima di sapere che anche l'ambiente M66 successivo e completo.

## Hotfix3 — risoluzione deterministica Helius prima del lock

Hotfix3 rimuove il probe Hotfix2 che richiedeva contemporaneamente
`DATABASE_PUBLIC_URL` e `HELIUS_API_KEY` nello stesso ambiente `railway run`
backend. Il database pubblico continua a provenire esclusivamente dal bootstrap
Railway `Postgres`; nessun fallback a `DATABASE_URL` viene introdotto.

La chiave Helius viene risolta prima del lock e senza chiamate al provider:

1. prova il servizio Railway `smartmoney-ai` rimuovendo prima
   `HELIUS_API_KEY` dall'ambiente padre, per evitare falsi positivi da variabili
   ereditate;
2. se Railway non esporta la chiave (incluso il caso sealed), usa `.env` locale;
3. come ultima sorgente usa una chiave già presente nel processo M73;
4. se nessuna sorgente contiene una chiave formalmente valida, fallisce prima
   del lock e prima di Helius.

La chiave selezionata viene passata soltanto nell'ambiente del subprocess M66,
mai nella command line, nei report o nei marker. stdout/stderr della corsia M66
vengono sanificati prima di essere mostrati. Hotfix3 non aggiunge `getHealth` o
altre richieste Helius di preflight: la prima richiesta reale resta quella della
corsia M66 originale e quindi rimane dentro il cap esistente di sei richieste /
600 crediti / zero retry.

Il lock one-shot, il recovery esatto del fallimento pre-network noto, gli hash
M66, il gate Gen4, il cap RPC pubblico, l'assenza signer/Paper/LIVE e tutte le
altre garanzie M73 restano invariati.


## Hotfix4 — local M63 credit guard enforcement

The controlled M66 lane executes locally against the Railway production database.
M63 normally becomes enforced through `ENVIRONMENT=production`; Hotfix4 does not
change the global environment. Instead it forces only the M66 subprocess to use:

- `HELIUS_CREDIT_GUARD_ENABLED=true`;
- `HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION=true`;
- `HELIUS_AUTOMATIC_ENHANCED_API_ENABLED=false`.

A zero-network Python preflight proves `_guard_enforced()` is true before the M73
one-shot lock is touched. The recovery token is limited to the exact Hotfix3
pre-provider failure state and is blocked if any M66/M73 network artifact appeared
after the Hotfix3 recovery timestamp. M66 hashes and 6-request/600-credit/0-retry
limits remain unchanged.
