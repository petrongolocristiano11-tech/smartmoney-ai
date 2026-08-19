# M72 — rotazione definitiva Discovery Gen4

M72 consuma esclusivamente i tre JSON firmati prodotti dalla M71 e trasforma il risultato economico in una decisione operativa esplicita. Non ripete l'analisi RPC e non esegue discovery: corregge le disposizioni generiche, ritira i profili senza un percorso difendibile, mantiene separati i wallet ancora osservabili e prepara un piano futuro disarmato.

## Risultato atteso sulla baseline reale

- 6 wallet attivi revisionati;
- 2 `OBSERVE_ONLY`: ATXu e F2Bn;
- 4 `RETIRED_FROM_PROMOTION`: 2sZak, 5N6i, 4jkL e DBqG;
- 0 `QUALIFIED_PENDING_SHORT_CANARY`;
- Bs34 resta `RESEARCH_ONLY_LOCKED` dopo il fallimento economico M65;
- ripetere M71 sugli stessi input non è raccomandato;
- servono nuovi candidati prima di poter raggiungere il consenso multi-wallet.

La classificazione distingue espressamente lo storico completo con campione insufficiente dallo storico incompleto. Un wallet sell-only o con parser yield definitivamente insufficiente non resta più nel generico `NEEDS_MORE_PUBLIC_RPC_HISTORY`.

## Piano futuro controllato

M72 prepara, ma non autorizza e non esegue, la corsia manuale M66 per acquisire nuovi wallet:

- massimo 6 richieste Helius;
- cap massimo 600 crediti;
- zero retry;
- conferma manuale futura separata: `AUTHORIZE_M72_CONTROLLED_HELIUS_DISCOVERY_LATER`;
- i candidati acquisiti dovranno poi passare dal parser canonico e dall'analisi economica M71 via cache/RPC pubblico;
- almeno due wallet indipendenti devono superare tutti i gate prima della short canary.

Questi valori sono soltanto il contratto del prossimo pacchetto eventualmente autorizzato. Installare o eseguire M72 produce zero richieste Helius e zero richieste di rete.

## Contratto di sicurezza

L'installazione e l'esecuzione M72 garantiscono:

- contatore ufficiale fermo a 83 e nessuna mutazione production;
- `RECOVERY_ONLY` escluso dalla prova real-time;
- zero rete, RPC pubblico, Helius e crediti Helius;
- zero letture o scritture database;
- zero POST backend e zero richieste Jupiter;
- zero paper, LIVE, firme e invii;
- nessuna modifica a signer, cron Discovery, campagna primaria o vecchio forward feed;
- nessun commit, push o deploy;
- output JSON atomici fuori dal repository.

## Input automatici

`RUN_M72_DEFINITIVE_DISCOVERY_ROTATION.ps1` cerca in `Downloads\smartmoney-audits` i file M71 più recenti:

1. `smartmoney-m71-adaptive-continuation-report-*.json`;
2. `smartmoney-m71-updated-m67-m70-report-*.json`;
3. `smartmoney-m71-adaptive-rpc-evidence-*.json`.

Tutti gli hash logici e i collegamenti incrociati vengono convalidati prima di produrre output.

## Output

La cartella `Downloads\smartmoney-audits` riceve:

- `smartmoney-m72-definitive-discovery-rotation-report-*.json`;
- `smartmoney-m72-controlled-new-wallet-acquisition-plan-disarmed-*.json`.

Il primo file è la decisione firmata; il secondo è il contratto disarmato per il futuro step controllato.

## Rollback

L'installer crea un backup esterno completo dei nove file M72 e uno script `ROLLBACK_M72_DEFINITIVE_DISCOVERY_ROTATION.ps1`. Il rollback ripristina esattamente lo stato precedente, rimuove solo i file che prima non esistevano e convalida nuovamente M71. Gli output read-only in `Downloads\smartmoney-audits` non vengono cancellati.
