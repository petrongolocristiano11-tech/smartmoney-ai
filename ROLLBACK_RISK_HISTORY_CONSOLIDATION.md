# Rollback

Prima di un rollback applicativo, disattiva il monitor:

```env
RUN_LIVE_POSITION_MONITOR=false
```

Per tornare alla migrazione precedente:

```powershell
.\.venv\Scripts\python.exe -m alembic downgrade d8a4f7c2e915
```

Poi ripristina il commit Git precedente e ridistribuisci backend e frontend.
