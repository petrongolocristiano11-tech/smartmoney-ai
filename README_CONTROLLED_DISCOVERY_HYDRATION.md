# SmartMoney AI — Controlled Discovery Hydration

Data blocco: 23 luglio 2026

## Obiettivo

Popolare l'Active Wallet Discovery con swap recenti reali senza riattivare lo stream continuo. Il blocco seleziona manualmente un numero limitato di wallet scoperti, interroga Helius una sola volta per wallet, salva e deduplica gli swap, conserva il timestamp reale e ricalcola Smart Score, attività, ranking e idoneità.

## Flusso

1. Selezione dei wallet con Smart Score più alto.
2. Esclusione predefinita dei wallet già attivi o iperattivi.
3. Cooldown di 12 ore dopo ogni tentativo.
4. Limite predefinito: 3 wallet e 3 richieste Helius.
5. Una richiesta HTTP per wallet; retry disabilitati nel batch Hydration.
6. Filtro Helius: `SWAP`, ultimi 7 giorni, massimo 100 transazioni.
7. Parsing e salvataggio con `block_time` reale.
8. Deduplica per firma della transazione.
9. Ricalcolo Smart Score, Activity Score, classe e idoneità.
10. Persistenza dell'esito Hydration per ogni wallet.

## Stati Hydration

- `NEVER`: wallet mai idratato.
- `COMPLETED`: swap recuperati e analizzati senza errori di parsing.
- `EMPTY`: nessuno swap trovato nel periodo richiesto.
- `PARTIAL`: almeno uno swap importato, con uno o più elementi non interpretabili.
- `FAILED`: richiesta Helius o elaborazione fallita.

## Endpoint manuale

```http
POST /discovered-wallets/hydration/run
```

Parametri:

- `max_wallets`: 1–10, predefinito 3;
- `max_helius_requests`: 1–10, predefinito 3;
- `lookback_days`: 1–14, predefinito 7;
- `transaction_limit`: 1–100, predefinito 100;
- `minimum_smart_score`: 0–100;
- `force`: predefinito `false`.

Il numero effettivo di wallet è sempre il minimo tra `max_wallets` e il budget richieste. Il batch non usa retry Helius automatici.

## Migrazione Alembic

Nuova head:

```text
b7d4e8f1c902
```

Revisione precedente:

```text
a3f7c9d2e641
```

Applicazione:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## Railway

Il backend deve continuare a eseguire `alembic upgrade head` prima dell'avvio applicativo. Non sono obbligatorie nuove variabili: i valori sicuri sono già predefiniti.

Variabili opzionali:

```text
DISCOVERY_HYDRATION_DEFAULT_WALLETS=3
DISCOVERY_HYDRATION_MAX_WALLETS_PER_RUN=10
DISCOVERY_HYDRATION_MAX_HELIUS_REQUESTS_PER_RUN=10
DISCOVERY_HYDRATION_LOOKBACK_DAYS=7
DISCOVERY_HYDRATION_TRANSACTION_LIMIT=100
DISCOVERY_HYDRATION_COOLDOWN_HOURS=12
```

Non modificare:

```text
RUN_LIVE_STREAM_WORKER=false
RUN_LIVE_POSITION_MONITOR=false
```

## Prima esecuzione sicura

Dopo il deploy:

1. aprire Discovery;
2. lasciare Wallet massimi = 3;
3. lasciare Budget richieste Helius = 3;
4. lasciare Storico = 7 giorni;
5. lasciare Transazioni = 100;
6. premere `Avvia idratazione controllata` una sola volta;
7. verificare `Helius: 3/3` o un numero inferiore;
8. controllare gli stati `COMPLETED`, `EMPTY`, `PARTIAL` o `FAILED`;
9. non premere `Applica wallet idonei`.

Le esecuzioni successive, senza `force`, passano automaticamente ai wallet successivi grazie al cooldown.

## Invarianti di sicurezza

- LIVE non viene abilitato o armato.
- Lo stream non viene avviato.
- Il worker resta IDLE.
- Non vengono create sottoscrizioni Helius.
- Nessun wallet viene applicato al worker.
- La Generazione #3 non viene resettata.
- La Generazione #4 non viene creata.
- Telegram e Discord non sono inclusi.
