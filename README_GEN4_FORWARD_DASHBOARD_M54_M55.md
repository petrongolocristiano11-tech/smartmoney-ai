# M54–M55 V3 Resume — Gen4 Forward Dashboard

Questa versione riprende l’installazione dopo il solo errore di avvio del verifier della V2.
La V2 aveva già completato con successo 1.274 test backend e il build Vite; il rollback aveva poi ripristinato i file prima di terminare.

## Correzione V3

Il verifier aggiunge autonomamente la root del progetto a `sys.path` prima degli import `backend`. Può quindi essere eseguito tramite percorso file da qualunque directory, anche senza `PYTHONPATH`.

L’installer V3:

- verifica campagna M52–M53 e revision Alembic `f4d6a9c2b813`;
- crea un nuovo backup;
- abilita il runtime shadow locale nel solo `.env`;
- riapplica dashboard, route e navigazione in modo idempotente;
- esegue il verifier da una directory esterna;
- esegue test mirati M52–M55;
- non ripete la suite completa, già conclusa con 1.274 test verdi nel tentativo V2 immediatamente precedente;
- esegue nuovamente il build frontend;
- verifica campagna e dashboard nel database;
- esegue rollback automatico se uno dei passaggi fallisce.

## Dashboard

Percorso locale:

```text
http://localhost:5173/gen4-forward
```

La dashboard mostra campagna, wallet congelati, cicli, decisioni, metriche Strict/proxy/baseline e avanzamento verso i requisiti di valutazione. Il ciclo manuale usa gli endpoint M52–M53 protetti da `X-Automation-Key` e non attiva paper o LIVE.
