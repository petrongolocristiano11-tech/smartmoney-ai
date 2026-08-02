# M56-M57 Gen4 Forward Feed — V4 Resume

Ripresa transazionale dopo il rollback automatico della V3.

La V4 elimina completamente `cmd.exe`, `call` e la quotatura di `npm.cmd`.
Il build frontend viene eseguito direttamente con:

`node.exe node_modules/npm/bin/npm-cli.js run build`

Questo funziona anche quando Node.js è installato in un percorso contenente spazi, come `C:\Program Files\nodejs`.

La V4 presuppone lo stato ripristinato dalla V3:

- Alembic `f4d6a9c2b813`;
- campagna Gen4 forward attiva;
- file M56-M57 ripristinati;
- suite backend completa già validata: 1284 test passati;
- nessun commit, push o deploy.

La ripresa esegue:

1. preflight semantico backend/frontend;
2. backup;
3. applicazione M56-M57;
4. upgrade Alembic ad `a5e7c1d4b926`;
5. 38 test mirati M47-M57;
6. build frontend via Node diretto;
7. attivazione feed;
8. verifier e primo poll controllato;
9. rollback automatico in caso di errore.

Sicurezza invariata: wallet congelati soltanto, point-in-time, nessun Jupiter, paper, signer o LIVE.
