# Rollback del milestone

Il rollback deve essere usato soltanto se il deploy non può essere corretto con un nuovo commit.

## Prima scelta: revert Git

Individua il commit del milestone e crea un revert:

```powershell
cd C:\smartmoney-ai
git log --oneline -5
git revert <HASH_COMMIT_MILESTONE>
git push origin main
```

## Database

La migrazione `d8a4f7c2e915` aggiunge tabelle e colonne. Il downgrade elimina anche i dati operativi raccolti dal nuovo monitor.

Eseguilo solo dopo avere fermato backend e worker e avere creato un backup PostgreSQL:

```powershell
.\.venv\Scripts\python.exe -m alembic downgrade c7d9e1f2a603
```

Non eseguire il downgrade mentre una versione del backend che usa i nuovi campi è ancora attiva.
