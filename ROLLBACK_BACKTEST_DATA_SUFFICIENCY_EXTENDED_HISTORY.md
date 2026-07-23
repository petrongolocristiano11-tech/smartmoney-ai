# Rollback — Backtest Data Sufficiency & Extended Candidate History

## Codice

Prima dell'applicazione lo script crea il branch:

```text
backup-before-extended-candidate-history-2026-07-23
```

Per ripristinare il codice locale:

```powershell
cd C:\smartmoney-ai
git reset --hard backup-before-extended-candidate-history-2026-07-23
```

Usare `reset --hard` soltanto dopo avere controllato che non esistano modifiche locali da conservare.

## Database locale

Per rimuovere la nuova migrazione:

```powershell
cd C:\smartmoney-ai
.\.venv\Scripts\python.exe -m alembic downgrade e4b7c2a9d815
```

Il downgrade elimina:

- tabella `candidate_history_backfill_runs`;
- tabella `candidate_token_compatibilities`;
- campi dello storico esteso;
- metriche di sufficienza e contatori cache aggiunti ai backtest;
- campi di sufficienza del ranking.

I trade storici già importati nella tabella `trades` non vengono cancellati automaticamente.

## Railway

Eseguire il rollback Railway soltanto se il deploy della nuova revisione non è utilizzabile. Ripristinare prima il commit precedente, quindi applicare il downgrade con una procedura controllata.

Non abilitare LIVE o stream durante il rollback e non modificare la Generazione #3.
