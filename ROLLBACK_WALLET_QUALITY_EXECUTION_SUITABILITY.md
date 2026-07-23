# Rollback Wallet Quality & Execution Suitability

Prima del push creare un branch di backup. Per tornare al database precedente:

```powershell
.\.venv\Scripts\python.exe -m alembic downgrade b7d4e8f1c902
```

Poi ripristinare il commit precedente tramite Git. Il downgrade rimuove esclusivamente i campi qualità aggiunti a `discovered_wallets` e `live_wallet_scores`.

Non usare il rollback mentre un deploy o una migrazione Railway sono in corso.
