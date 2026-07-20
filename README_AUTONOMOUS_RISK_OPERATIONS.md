# SmartMoney AI — Uscite autonome, rischio e operazioni

Milestone completo per trasformare il motore DRY_RUN in un sistema capace di monitorare le posizioni, applicare regole di uscita, bloccare nuovi BUY quando il rischio supera i limiti e riconciliare gli ordini LIVE con Solana.

## Sicurezza iniziale

Il pacchetto mantiene:

- modalità LIVE non attivata;
- monitor automatico disabilitato di default;
- simulazione LIVE e armamento temporaneo già esistenti;
- chiavi e file `.env` esclusi dallo ZIP.

Dopo l'installazione lascia in Railway:

```env
RUN_LIVE_POSITION_MONITOR=false
```

Prima si verifica manualmente il funzionamento in DRY_RUN dalla nuova scheda **Automazione e rischio**.

## Funzionalità incluse

### Motore automatico di uscita

- Take profit.
- Stop loss.
- Trailing stop basato sul massimo valore raggiunto.
- Chiusura per durata massima della posizione.
- Uscita totale o percentuale.
- Priorità deterministica: stop loss, trailing stop, take profit, time exit.
- Blocco delle chiusure duplicate e cooldown tra tentativi falliti.
- Quotazione Jupiter reale anche in DRY_RUN.
- Supporto predisposto per DRY_RUN e LIVE, senza aggirare armamento, signer e simulazione.

### Gestione completa del rischio

- Numero massimo di posizioni aperte.
- Esposizione massima per token.
- Esposizione totale già esistente.
- Numero massimo di ordini giornalieri.
- Drawdown massimo di portafoglio.
- Serie di perdite consecutive.
- Cooldown automatico dei nuovi BUY.
- Reset manuale del cooldown con conferma esplicita.
- Equity corrente, picco, PnL realizzato e PnL non realizzato.

I SELL restano consentiti per permettere l'uscita dalle posizioni anche quando i nuovi BUY sono bloccati dal rischio.

### Monitor e riconciliazione

- Worker periodico con lease database per evitare esecuzioni duplicate.
- Heartbeat e stato `STOPPED`, `IDLE`, `RUNNING`, `DEGRADED` o `ERROR`.
- Aggiornamento periodico di valore, PnL e ROI delle posizioni.
- Metriche cumulative su quote, uscite ed errori.
- Riconciliazione delle firme LIVE tramite `getSignatureStatuses`.
- Stati ordine `PENDING`, `CONFIRMED`, `FAILED`, `UNKNOWN` e `NOT_REQUIRED`.

### Dashboard

Nuova scheda **Automazione e rischio** con:

- equity e drawdown;
- stato e heartbeat monitor;
- posizioni e uscite pendenti;
- metriche quote e uscite;
- riconciliazione ordini LIVE;
- ciclo manuale;
- reset del cooldown;
- configurazione completa TP, SL, trailing, time exit e limiti di rischio.

## Installazione manuale

1. Verifica che il lavoro precedente sia già su GitHub.
2. Fai una copia di sicurezza della cartella `C:\smartmoney-ai`.
3. Estrai lo ZIP direttamente dentro `C:\smartmoney-ai`.
4. Quando Windows lo chiede, scegli **Sostituisci i file nella destinazione**.
5. Non copiare né modificare `.env` tramite lo ZIP.

Esegui:

```powershell
cd C:\smartmoney-ai
Set-ExecutionPolicy -Scope Process Bypass
.\TEST_AUTONOMOUS_RISK_OPERATIONS.ps1
```

Risultati attesi:

```text
168 passed
11 test Node superati
Endpoint operativi: 4/4
Migrazione corrente: d8a4f7c2e915
ESLint file modificati: superato
Build frontend: superata
```

## Primo collaudo in browser

Dopo il deploy:

1. Apri **Live Trading → Controllo e policy**.
2. Mantieni `DRY_RUN` e LIVE non armato.
3. Imposta soglie prudenti, per esempio TP 25%, SL 15%, trailing inizialmente spento.
4. Salva la policy con `sell_enabled=true`.
5. Apri **Automazione e rischio**.
6. Premi **Esegui un ciclo ora**.
7. Verifica valore corrente, ROI, motivo di uscita e metriche.
8. Controlla **Ordini**, **Posizioni** ed **Eventi**.

Il ciclo manuale può aggiornare le quotazioni anche con le uscite automatiche spente. Genera un SELL autonomo soltanto quando `automatic_exits_enabled=true` e una soglia è raggiunta.

## Attivazione successiva del monitor periodico

Solo dopo almeno un ciclo manuale DRY_RUN corretto, imposta sul backend Railway:

```env
RUN_LIVE_POSITION_MONITOR=true
LIVE_POSITION_MONITOR_INTERVAL_SECONDS=30
LIVE_POSITION_MONITOR_LEASE_SECONDS=120
LIVE_POSITION_MONITOR_BATCH_SIZE=100
LIVE_ORDER_RECONCILE_BATCH_SIZE=50
```

Poi fai redeploy del backend e verifica nei log:

```text
embedded_position_monitor_started
position_monitor_starting
```

La modalità operativa deve restare `DRY_RUN`. L'attivazione del worker non autorizza automaticamente il LIVE.

## Commit e push

Dopo tutti i test:

```powershell
git status --short
git diff --check

git add `
  .env.example `
  alembic `
  backend `
  frontend/src `
  scripts/verify_autonomous_risk_operations.py `
  tests `
  TEST_AUTONOMOUS_RISK_OPERATIONS.ps1 `
  README_AUTONOMOUS_RISK_OPERATIONS.md `
  ROLLBACK_AUTONOMOUS_RISK_OPERATIONS.md `
  TEST_RESULTS_AUTONOMOUS_RISK_OPERATIONS.txt `
  PATCH_MANIFEST_SHA256.txt

git commit -m "feat: add autonomous exits risk controls and operations monitor"
git push origin main

git status
git log -1 --oneline
```

Controlla che `.env` non compaia mai nel commit.

## Nota ESLint

Il gate del pacchetto esegue ESLint sui quattro file frontend modificati. Il comando globale `npm run lint` del repository contiene già segnalazioni in componenti non modificati da questo milestone; non sono state nascoste né considerate come errori introdotti dal pacchetto.
