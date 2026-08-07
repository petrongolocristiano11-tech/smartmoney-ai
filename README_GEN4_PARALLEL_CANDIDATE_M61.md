# SmartMoney AI — M61 Gen4 Parallel Qualified-Candidate Copyability

## Scopo

M61 aggiunge una seconda campagna Gen4 Copyability isolata per wallet rigidamente qualificati, senza alterare la campagna M58-M60 primaria già in raccolta.

Wallet candidato approvato per la prima attivazione M61:

`Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd`

Campagna primaria M58-M60 che deve rimanere invariata:

`89026d62-1e4e-452b-b0bf-8a5e3dd373e4`

Anchor primario congelato:

`2026-08-03T23:04:08.419988+00:00`

Wallet primari congelati:

- `FsKYLBwxLQk5YMNSPYQcqceW6o8tJGF7U1aBHyEvGAyE`
- `2ZwYWRaQR7X3zcD7VX8u4Ke8znPQuKrVpRnU3Tp6UH7S`

## Architettura

M61 introduce due ruoli immutabili a livello di campagna:

- `PRIMARY_FORWARD`: la campagna M58-M60 esistente, sempre selezionata come default per retrocompatibilità.
- `QUALIFIED_CANDIDATE`: una campagna parallela con proprio campaign ID, anchor, receipts, posizioni, PnL e proof clock.

La vecchia relazione one-to-one tra Forward e Copyability viene sostituita da:

- più campagne Copyability per la stessa Forward lineage;
- una sola `PRIMARY_FORWARD` per `forward_campaign_db_id`, protetta da unique index parziale PostgreSQL;
- `candidate_key` univoco per ogni run candidato immutabile;
- `selection_snapshot` persistito come evidenza storica di ammissione, ma escluso dalla prova forward.

## Isolamento delle evidenze

Un singolo Helius Raw Webhook monitora l'unione dei wallet attivi. Il backend effettua il routing per campagna e persiste una receipt separata per `campaign_db_id`.

La chiave di deduplica resta per-campagna: `(campaign_db_id, signature)`.

Questo significa che:

- i contatori della primaria non vengono azzerati;
- l'anchor della primaria non viene modificato;
- le posizioni della candidata non vengono sommate alla primaria;
- PnL, drawdown, profit factor e closed trades restano isolati;
- recovery polling resta `RECOVERY_ONLY / EXCLUDED_RECOVERY` e non entra nella prova real-time.

## Helius

M61 non crea un secondo webhook. Durante l'attivazione aggiorna esclusivamente il Raw Webhook Gen4 già esistente da 2 a 3 indirizzi e registra lo stesso webhook sulle due campagne.

L'attivazione rifiuta:

- webhook Gen4 mancante;
- webhook con URL inatteso;
- indirizzi esistenti diversi dai due wallet primari o dalla union già valida dei tre wallet;
- sovrapposizioni di wallet tra campagne attive.

Il configuratore legacy M58-M60 è stato reso M61-aware e usa anch'esso l'unione delle campagne attive.

## Sicurezza di trading

M61 non introduce alcun percorso di esecuzione reale.

- signer: assente;
- private key: assente;
- firma: assente;
- submit/send: assente;
- Paper: non attivato;
- LIVE: non attivato;
- Jupiter: quote + unsigned build secondo il contratto M58-M60;
- attivazione LIVE automatica: `false`.

## Alembic

Parent:

`b6f8d2e4c731`

M61 head:

`c8a1f3d6e942`

La migrazione:

1. aggiunge `campaign_role`, `candidate_key`, `selection_snapshot`;
2. backfilla tutte le righe M58-M60 esistenti come `PRIMARY_FORWARD`;
3. elimina la vecchia unique completa su `forward_campaign_db_id`;
4. aggiunge unique `candidate_key`;
5. aggiunge unique index parziale per impedire due primarie sulla stessa Forward lineage;
6. preserva i campi e contatori della campagna primaria.

Il downgrade viene rifiutato se esiste evidenza di campagne candidate parallele. Non viene effettuata cancellazione automatica di evidenze.

## Installazione locale — primo step obbligatorio

Eseguire soltanto `INSTALL_TEST_M61_LOCAL.ps1` dal pacchetto estratto.

L'installer locale:

- verifica manifest SHA-256;
- verifica esattamente la baseline M58-M60 V8 dei file che M61 deve sostituire;
- richiede branch `main` e worktree pulita;
- richiede Alembic `b6f8d2e4c731` prima dell'installazione;
- crea backup dei file e dump PostgreSQL locale;
- applica file completi;
- migra a `c8a1f3d6e942`;
- esegue roundtrip PostgreSQL upgrade/downgrade/upgrade quando non esistono candidate reali;
- confronta la snapshot primaria prima/dopo;
- esegue test mirati M47-M61;
- esegue l'intera suite backend;
- esegue build Vite produzione;
- esegue verifier OpenAPI/sicurezza;
- esegue `git diff --check`;
- non esegue commit, push o deploy.

Durante questo step:

- Helius network calls: 0;
- Jupiter network calls: 0;
- Railway modifications: 0;
- candidate campaign creation: 0.

Se uno dei gate fallisce, l'installer prova a ripristinare migrazione e file dal backup locale e termina con exit code non zero.

## Deploy e attivazione — solo dopo PASS locale

`DEPLOY_ACTIVATE_M61.ps1` non parte automaticamente.

Richiede conferma testuale esatta:

`DEPLOY_AND_ACTIVATE_M61_PARALLEL_CANDIDATE`

Prima di modificare Railway:

- verifica M61 locale alla head corretta;
- verifica che le modifiche Git siano esclusivamente quelle previste;
- legge i segreti localmente senza stamparli;
- controlla la head del database Railway;
- crea un dump remoto PostgreSQL.

Il deploy è resumable: accetta in sicurezza sia lo stato iniziale `b6f8d2e4c731`, sia una precedente esecuzione M61 parziale già migrata a `c8a1f3d6e942`; riconosce anche un commit M61 locale già creato e pulito senza crearne un secondo.

L'attivazione:

1. verifica ID, anchor e due wallet della primaria;
2. crea o riusa idempotentemente la candidata;
3. aggiorna il webhook esistente alla union di 3 wallet;
4. registra lo stesso webhook sulle due campagne;
5. verifica la union Helius;
6. verifica che i contatori primari non siano regrediti;
7. verifica tutti i guardrail no-signer/no-Paper/no-LIVE.

## Fail-safe attivazione

Se l'attivazione fallisce dopo aver modificato il webhook:

- prova a ripristinare gli indirizzi originali del webhook;
- ferma soltanto la candidata creata dalla stessa attivazione;
- se trova una candidata preesistente proveniente da una precedente attivazione incompleta e non ancora monitorata, la ferma anch'essa;
- non ferma mai la primaria;
- non cancella evidenza persistita.

## Rollback operativo M61

`ROLLBACK_M61_SAFE.ps1` richiede:

`ROLLBACK_M61_CANDIDATE_ONLY`

Il rollback operativo:

- ferma soltanto le campagne candidate attive;
- ripristina il webhook ai due wallet primari;
- registra nuovamente il webhook sulla primaria;
- verifica ID/anchor/wallet/contatori primari;
- conserva tutte le righe e le evidenze candidate;
- non esegue downgrade Alembic;
- non esegue Git revert;
- non abilita Paper/LIVE.

## Verifica candidato usata per l'ammissione

Snapshot di selezione persistita dalla prima attivazione:

- activity gate: PASS;
- BUY/SELL parsing: PASS;
- quality gate: PASS;
- observed profitability: PASS;
- Gen4 copyability: PASS;
- 74 swap / 7d;
- 49 swap / 24h;
- 45 BUY / 29 SELL / 0 UNKNOWN;
- 9 unique token;
- 9 completed token pairs;
- observed PnL: +1.702192 SOL;
- observed win rate: 51.85%;
- observed profit factor: 1.4252;
- Jupiter copyability: 6/6 con input 0.01 SOL e slippage 300 bps.

Questa snapshot autorizza soltanto l'ingresso nella nuova campagna. Non viene conteggiata come forward proof.

## Regola operativa

Non modificare manualmente `frozen_wallets`, `anchor_at`, `alembic_version`, receipt, position o contatori. Non aggiungere direttamente il candidato al webhook fuori dallo script M61. Non utilizzare `alembic stamp` come scorciatoia.

## V2 local-installer hardening

The local PostgreSQL database is allowed to contain zero M58-M60 copyability campaign rows. The production primary campaign is verified only during deploy preflight against Railway. Local installation snapshots and preserves the complete local campaign row-set (including an empty set), disables the embedded copyability runtime only in child test processes, and never changes `.env` for this purpose.

## V3 whitespace/diff hardening

V3 removes the extra blank line at EOF in `backend/app/services/blockchain_parser_gen4_copyability_service.py` that caused `git diff --check` to exit 2 on Windows after every functional test had already passed. The M61 code and migration contract are unchanged. The package payload has been checked for trailing whitespace / blank EOF and the seven tracked M58-M60 files modified by M61 have been overlaid on the exact M58-M60 V8 baseline in a temporary Git repository; `git diff --check` returns exit code 0.
