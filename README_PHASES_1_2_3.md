# SmartMoney AI — Fasi 1, 2 e 3

Questo pacchetto si applica sopra il progetto che contiene già:

- generazioni DRY_RUN;
- parser Helius SOL swap;
- chiusura manuale controllata delle posizioni DRY_RUN.

## Fase 1 — Portfolio Analytics

Aggiunge una nuova scheda **Analytics e sicurezza** con:

- equity curve e PnL cumulativo;
- PnL realizzato, ROI, win rate e profit factor;
- drawdown massimo;
- performance per wallet e per token;
- posizioni chiuse recenti;
- esportazione CSV per modalità e generazione.

## Fase 2 — Ranking e Token Safety

Aggiunge:

- ranking fino a 50 wallet sorgente;
- Smart Score combinato tra profilo storico e risultati copy-trading;
- selezione controllata dei wallet idonei;
- allowlist e blocklist token;
- filtri su liquidità, market cap, volume 24h e concentrazione holder;
- controlli mint authority e freeze authority;
- verifica di vendibilità tramite quotazione Jupiter;
- integrazione RugCheck esterna facoltativa;
- snapshot di sicurezza persistenti e audit.

I SELL non vengono bloccati dai filtri token, così il sistema può sempre uscire da una posizione.

## Fase 3 — Hardening LIVE

Aggiunge:

- readiness checklist completa;
- verifica corrispondenza signer/wallet;
- verifica saldo operativo;
- token safety fail-closed obbligatoria per la readiness;
- simulazione Solana obbligatoria prima dell’invio;
- armamento LIVE temporaneo con scadenza automatica;
- disarmo automatico passando a DRY_RUN/DISABLED o attivando il kill switch;
- blocco degli ordini LIVE quando la finestra non è armata.

Il pacchetto non contiene `.env`, API key o chiavi private. Non abilita automaticamente LIVE.

## Test completati sul pacchetto

- `141 passed` — suite backend completa;
- `python -m compileall backend` superato;
- OpenAPI caricato con 11 route della nuova piattaforma;
- migrazione PostgreSQL generata e validata in modalità SQL offline;
- ESLint superato sui file frontend modificati;
- `npm run build` superato.

Non è stata inviata alcuna transazione reale on-chain durante i test. La pipeline LIVE è stata verificata con test isolati di armamento, firma simulata, `simulateTransaction` e invio Jupiter simulato.

## Dopo l’estrazione

Esegui dalla cartella `C:\smartmoney-ai`:

```powershell
.\TEST_FINALE_PHASES_1_2_3.ps1
```

Railway eseguirà automaticamente `alembic upgrade head` durante il pre-deploy tramite la configurazione già presente nel progetto.
