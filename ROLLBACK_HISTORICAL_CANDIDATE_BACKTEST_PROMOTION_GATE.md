# Rollback — Historical Candidate Backtest & Promotion Gate

## Rollback del codice prima del push

La procedura di applicazione crea il branch:

```text
backup-before-candidate-backtest-promotion-2026-07-23
```

Per tornare al codice precedente prima del commit:

```powershell
cd C:\smartmoney-ai
git reset --hard backup-before-candidate-backtest-promotion-2026-07-23
```

## Rollback della migrazione locale

```powershell
cd C:\smartmoney-ai
.\.venv\Scripts\python.exe -m alembic downgrade c9e4a7f2d631
```

Il downgrade elimina la tabella dei backtest e i campi riassuntivi del Promotion Gate. Non ripristina automaticamente wallet idonei: dopo un rollback è necessario controllare manualmente lo stato del ranking prima di qualsiasi applicazione.

## Sicurezza

Durante rollback lasciare LIVE disabilitato, stream spento, worker IDLE e Generazione #3 invariata. Non creare la Generazione #4 e non applicare wallet.
