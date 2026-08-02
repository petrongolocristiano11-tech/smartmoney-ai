# M52-M53 Gen4 Strict Forward Shadow — V3 transazionale

Questa versione sostituisce i controlli fragili basati su hash o marker testuali con verifiche runtime e una patch semantica idempotente.

## Garanzie

- Verifica M51 importando il codice e leggendo la policy reale.
- Non sovrascrive integralmente `main.py` o altri file condivisi.
- Crea un backup prima di ogni modifica.
- Esegue patch, compilazione, test mirati, OpenAPI, upgrade/downgrade/upgrade e suite completa.
- Avvia la campagna solo dopo tutti i controlli verdi.
- In caso di errore prima dell'avvio, ripristina automaticamente file e revisione Alembic.
- Nessun Helius, Jupiter, paper, signer, worker, scheduler, submit o LIVE.

## Avvio

Eseguire `INSTALL_AND_START_GEN4_FORWARD_M52_M53_V3.py` con il Python del virtual environment del progetto.
