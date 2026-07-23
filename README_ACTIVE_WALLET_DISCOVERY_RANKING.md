# Active Wallet Discovery & Ranking

## Obiettivo

Questo blocco aggiunge un filtro di attività recente prima che un wallet possa risultare idoneo nel ranking. Non abilita lo stream, non arma LIVE, non applica automaticamente wallet, non resetta la Generazione DRY_RUN #3 e non crea la Generazione #4.

## Metriche salvate

Per ogni wallet scoperto vengono calcolati e persistiti:

- ultimo swap;
- swap, BUY e SELL nelle ultime 24 ore e negli ultimi 7 giorni;
- volume SOL nelle ultime 24 ore e negli ultimi 7 giorni;
- giorni attivi negli ultimi 7 giorni;
- swap medi per giorno attivo;
- minuti medi tra gli swap;
- Activity Score;
- classificazione `ATTIVO`, `POCO_ATTIVO`, `INATTIVO`, `IPERATTIVO`;
- Ranking Score e idoneità finale.

`INATTIVO` e `IPERATTIVO` sono esclusi. `POCO_ATTIVO` resta visibile, riceve uno score attività limitato e può essere valutato dal ranking insieme agli altri vincoli.

## Railway — backend

Il file `railway.json` esegue già automaticamente:

```bash
alembic upgrade head
```

Dopo il push:

1. aprire il deploy del servizio backend;
2. verificare nei log che la revisione `a3f7c9d2e641` sia stata applicata;
3. verificare che il servizio torni `Healthy` sull'endpoint `/ready`;
4. lasciare `RUN_LIVE_STREAM_WORKER=false`;
5. lasciare `RUN_LIVE_POSITION_MONITOR=false`;
6. non impostare chiavi private LIVE e non armare LIVE.

Non servono nuove variabili Railway per questo blocco.

## Railway — frontend

Eseguire il normale redeploy del servizio frontend. La pagina Discovery mostra le nuove metriche e il ranking LIVE espone la classificazione attività. Prima del push locale eseguire `npm ci` e `npm run build`; Railway userà il `package-lock.json` già presente.

## Primo utilizzo sicuro

1. Aprire **Discovery Center**.
2. Premere **Ricalcola attività DB** per aggiornare i wallet storici usando solo i trade già salvati. Questa operazione esegue zero richieste Helius.
3. Eseguire una nuova Discovery solo su seed realmente attivi quando si desidera importare dati recenti da Helius.
4. Controllare classificazione, ultimo swap, swap 24h/7d, BUY/SELL, volume, giorni attivi e idoneità.
5. Non premere **Applica wallet idonei** finché il ranking non è stato verificato manualmente.

## Verifiche locali

```powershell
$env:DATABASE_URL="sqlite+pysqlite:///:memory:"
$env:SOLANA_RPC_URL="https://example.invalid"
$env:HELIUS_API_KEY="test-key"
$env:ENVIRONMENT="test"

python -m compileall backend
python -m pytest -q

cd frontend
npm install
npm run build
```
