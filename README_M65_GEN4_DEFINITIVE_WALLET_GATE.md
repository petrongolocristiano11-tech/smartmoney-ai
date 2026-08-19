# M65 — Gate definitivo di qualificazione wallet Gen4

## Scopo

M65 prende esclusivamente i due artefatti firmati dall'audit M64 — report
83+17 e raw evidence pubblico — e produce una decisione deterministica,
locale e read-only sul wallet candidato
`Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd`.

M65 non modifica la campagna e non autorizza Micro Live. Il suo massimo esito
positivo è `PASS_FOR_MICRO_LIVE_PREPARATION`; l'esecuzione richiede comunque
un futuro step separato e un'autorizzazione esplicita dell'utente.

## Catena dell'evidenza

Prima di calcolare il gate, il runner verifica:

- versione, scope e hash del report M64;
- hash di ogni trade ufficiale, ricostruito e supplementare;
- ricalcolo indipendente di PnL, return, profit factor, win rate e drawdown;
- corrispondenza nome e SHA-256 del raw evidence con il report M64;
- hash interno e completezza della scansione pubblica;
- contatore ufficiale 83 e campione analitico 17, senza promozione a prova
  real-time;
- zero Helius, backend POST, database write, Jupiter storico, paper/LIVE,
  firma o submission.

Un mismatch interrompe l'esecuzione in fail-closed e non produce una decisione
utilizzabile.

## Gate economico congelato

| Controllo | Soglia M65 |
| --- | ---: |
| campione combinato | almeno 100 chiusi |
| PnL combinato | maggiore di 0 |
| profit factor combinato | almeno 1,20 |
| drawdown combinato | massimo 20% |
| campione recente ricostruito | almeno 17 chiusi |
| PnL recente | maggiore di 0 |
| profit factor recente | almeno 1,00 |
| drawdown recente | massimo 20% |
| token distinti | almeno 5 |
| concentrazione sul token principale | massimo 40% |
| PnL senza il miglior trade | maggiore di 0 |
| finestre positive da 20 trade | almeno 3 su 5 |
| peggior PF nelle finestre da 20 | almeno 0,70 |
| reject rate ufficiale entrate | massimo 20% |
| posizioni pubbliche ricostruite aperte | zero |
| storia pubblica | completa fino al confine M63 |
| sensitivity batch completo | PnL positivo e PF almeno 1,20 |

Il campione 83+17 resta l'oggetto principale. Quando il 17º trade appartiene a
una transazione che chiude più posizioni, M65 valuta obbligatoriamente anche il
batch intero come sensitivity, senza cambiare il contatore ufficiale.

## Canary real-time obbligatorio per qualunque esito positivo

Anche se tutti i controlli economici passano, senza canary l'esito è soltanto
`CONDITIONAL_PASS_CANARY_REQUIRED`. Il canary shadow deve essere hash-bound e
rispettare almeno:

- 24 ore osservate, 20 tentativi di entrata e 10 trade chiusi;
- coverage webhook almeno 95% e build unsigned 100%;
- reject rate massimo 20%;
- P95 end-to-quote massimo 5.000 ms;
- P95 price impact massimo 500 bps;
- P95 price deterioration massimo 1.000 bps;
- zero posizioni aperte e zero failure irrisolti;
- zero signer, ordini paper/LIVE, firme o submission.

Il canary non viene creato da M65 e non viene fabbricato dal passato. È un input
opzionale futuro, separato e verificato.

## Esiti

| Esito | Significato | Passo consentito |
| --- | --- | --- |
| `FAIL_ECONOMIC` | uno o più controlli storici/recenti falliscono | Discovery copyability-aware |
| `CONDITIONAL_PASS_CANARY_REQUIRED` | economia idonea, canary assente | raccogliere un canary shadow |
| `FAIL_CANARY` | economia idonea, canary non idoneo | correggere e ripetere il canary |
| `PASS_FOR_MICRO_LIVE_PREPARATION` | economia e canary idonei | solo preparazione Micro Live |

In ogni esito: `MICRO_LIVE_EXECUTION_AUTHORIZED=NO`, signer non autorizzato e
attivazione automatica LIVE disabilitata.

## Risultato di regressione della candidata corrente

La fixture di regressione conserva i dati osservati dall'audit corrente:

- 83 ufficiali: `+32.319.569` lamport;
- 17 ricostruiti: `-13.864.963` lamport;
- 83+17: `+18.454.606` lamport, profit factor circa `1,1225`;
- batch completo 83+20: profit factor circa `1,1542`.

La candidata resta quindi `FAIL_ECONOMIC` e
`RESEARCH_ONLY_RECENT_STABILITY_FAILED`. Questo risultato non è incorporato a
forza nel runner: la fixture protegge la regressione, mentre il gate ricalcola
sempre gli artefatti M64 selezionati.

## Esecuzione

Per generare prima l'audit M64 e poi il gate M65 in un solo flusso:

```powershell
powershell.exe -ExecutionPolicy Bypass -File C:\smartmoney-ai\RUN_M65_FULL_READONLY_AUDIT_AND_GATE.ps1
```

Gli output vengono salvati per default in
`%USERPROFILE%\Downloads\smartmoney-audits`, fuori dal repository.

Per rieseguire il solo gate su una coppia M64 già prodotta:

```powershell
powershell.exe -ExecutionPolicy Bypass -File C:\smartmoney-ai\RUN_M65_GEN4_DEFINITIVE_WALLET_GATE.ps1
```

## Installazione e rollback

L'installer cumulativo richiede branch `main`, HEAD
`fe63c528e55af84a97d6deb6872e825a5a43c6b4` e worktree pulita. Installa M64
corretto e M65 in un unico step, crea un backup esterno, verifica ogni SHA-256,
esegue compileall, verifier M58–M65, test mirati M58–M65, Alembic heads, suite
completa e `git diff --check`. In caso di errore effettua rollback automatico.

Non esegue commit, push, deploy, migrazioni, Railway mutation o scritture
production. Discovery, campagna primaria, vecchio forward feed, LIVE e signer
restano invariati.
