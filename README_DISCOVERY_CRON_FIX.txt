SMARTMONEY AI — FIX DEFINITIVO DISCOVERY / HELIUS / CRON RAILWAY
================================================================

OBIETTIVO
---------
Questo pacchetto corregge il crash del servizio smartmoney-cron causato da un
HTTP 500 temporaneo di Helius durante la Discovery.

La correzione interviene contemporaneamente su:

1. client Helius con retry e backoff;
2. protezione delle chiavi nei log;
3. isolamento degli errori per singolo wallet e singolo token;
4. risultati Discovery COMPLETED / PARTIAL / FAILED;
5. rollback della sessione database dopo un errore;
6. cron Railway in stato DEGRADED, senza falso crash, quando la Discovery
   fallisce ma il Paper Autopilot termina correttamente;
7. test automatici Python e Node.

IMPORTANTE PRIMA DEL DEPLOY
--------------------------
La vecchia HELIUS_API_KEY è comparsa in un log condiviso. Considerala
compromessa:

- genera una nuova chiave nella dashboard Helius;
- sostituisci HELIUS_API_KEY nelle Variables di smartmoney-backend;
- elimina o disattiva la vecchia chiave dopo aver verificato il redeploy;
- non copiare mai URL completi contenenti ?api-key= nei messaggi o screenshot.

COME COPIARE I FILE
-------------------
1. Fai un backup oppure verifica che il lavoro corrente sia già in Git.
2. Apri questo ZIP.
3. Copia TUTTO il contenuto direttamente in:

   C:\smartmoney-ai

4. Quando Windows lo chiede, scegli "Sostituisci i file nella destinazione".
5. Non sostituire e non cancellare il tuo file .env.

Il pacchetto contiene .env.example, non contiene .env e non contiene segreti.
Non è necessaria alcuna migrazione Alembic.

FILE MODIFICATI
---------------
.env.example
backend/app/core/config.py
backend/app/services/helius.py
backend/app/services/wallet_sync_service.py
backend/app/services/discovery_engine.py
automation/run.mjs
automation/run.test.mjs

FILE NUOVI
----------
tests/test_helius_resilience.py
tests/test_discovery_resilience.py
TEST_DISCOVERY_CRON_RESILIENCE.ps1
README_DISCOVERY_CRON_FIX.txt
TEST_RESULTS_DISCOVERY_CRON_FIX.txt
PATCH_MANIFEST_SHA256.txt

NUOVA GESTIONE HELIUS
---------------------
I codici 429, 500, 502, 503 e 504 vengono ritentati automaticamente.
Configurazione predefinita:

HELIUS_REQUEST_TIMEOUT_SECONDS=20
HELIUS_MAX_RETRIES=3
HELIUS_RETRY_BASE_SECONDS=0.75
HELIUS_RETRY_MAX_SECONDS=8

HELIUS_MAX_RETRIES=3 significa: prima richiesta + massimo 3 nuovi tentativi.
Le variabili sono facoltative perché il backend contiene già valori sicuri di
default. Puoi aggiungerle su Railway per renderle esplicite.

COMPORTAMENTO DOPO IL FIX
-------------------------
- un singolo wallet Helius fallito non interrompe gli altri wallet;
- un singolo token Helius fallito non interrompe gli altri token;
- il backend restituisce status PARTIAL o FAILED senza generare un 500 per un
  normale errore temporaneo del provider;
- la chiave Helius non compare nelle eccezioni create dal nuovo client;
- se Discovery fallisce ma Autopilot riesce, il cron termina con status
  DEGRADED e codice di uscita 0;
- Railway non dovrebbe più classificare quel caso come Deployment Crashed;
- backend irraggiungibile, configurazione mancante o Autopilot completamente
  fallito restano errori critici con codice di uscita 1.

TEST LOCALE
-----------
Apri PowerShell nella cartella principale ed esegui:

cd C:\smartmoney-ai
Set-ExecutionPolicy -Scope Process Bypass
.\TEST_DISCOVERY_CRON_RESILIENCE.ps1

Risultato atteso per la suite aggiornata:

154 passed
11 test Node superati
frontend build completata

Se nel frattempo hai aggiunto altri test, il totale Python potrà essere
superiore a 154.

COMMIT E PUSH
-------------
Dopo i test:

git status --short

git add .env.example automation backend/app/core/config.py `
  backend/app/services/helius.py `
  backend/app/services/wallet_sync_service.py `
  backend/app/services/discovery_engine.py `
  tests/test_helius_resilience.py `
  tests/test_discovery_resilience.py `
  TEST_DISCOVERY_CRON_RESILIENCE.ps1 `
  README_DISCOVERY_CRON_FIX.txt `
  TEST_RESULTS_DISCOVERY_CRON_FIX.txt `
  PATCH_MANIFEST_SHA256.txt

git commit -m "fix: harden Helius discovery and cron execution"
git push origin main
git status
git log -1 --oneline

RAILWAY — ORDINE CORRETTO
-------------------------
1. Ruota HELIUS_API_KEY.
2. Attendi il redeploy di smartmoney-backend.
3. Verifica /ready e che restituisca status ready.
4. Nel servizio smartmoney-cron imposta:

   DISCOVERY_ENABLED=true
   AUTOPILOT_ENABLED=true

5. Fai Redeploy del cron.

LOG ATTESO IN CASO DI NUOVO ERRORE TEMPORANEO HELIUS
----------------------------------------------------
Il cron potrà mostrare:

discovery_partial oppure discovery_failed
autopilot_completed
automation_completed con status DEGRADED

Il container cron terminerà normalmente. Non deve comparire
automation_crashed soltanto perché Helius ha fallito la Discovery.

STATO DI SICUREZZA
------------------
Mantieni:

- trading in DRY_RUN;
- LIVE non armato;
- chiave privata LIVE non configurata finché non inizieremo il collaudo LIVE;
- Token Safety attivo in fail-closed per i nuovi BUY.
