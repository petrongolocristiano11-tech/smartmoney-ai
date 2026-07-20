# SmartMoney AI — consolidamento storico rischio

## Correzioni incluse

- Ricostruzione deterministica della serie di perdite dagli ordini SELL completati.
- Inclusione di chiusure `MANUAL_CLOSE`, `AUTO_EXIT` e SELL provenienti dal wallet sorgente.
- Le tre chiusure manuali negative già presenti vengono riconosciute senza doverle ripetere.
- Il cooldown viene attivato solo se l'ultima perdita è ancora dentro la finestra configurata.
- Le perdite vecchie restano visibili nella serie, ma non creano un cooldown scaduto.
- Il reset manuale salva un checkpoint: lo storico PnL resta intatto e le vecchie chiusure non vengono ricontate nella serie.
- Eliminazione del possibile doppio conteggio dopo un nuovo SELL.
- Dettaglio posizioni con valore corrente, PnL non realizzato, ROI, ultima quotazione e stato uscita.
- Dettaglio dell'ultimo ciclo manuale per ogni posizione.
- Test DRY_RUN che verifica quotazione e trigger senza chiudere quando le uscite automatiche sono spente.

## Migrazione

Nuova revisione Alembic:

```text
e2f9a6b4c731
```

Aggiunge il campo nullable:

```text
live_risk_states.loss_streak_reset_at
```

## Installazione

1. Verifica di partire da un commit pulito.
2. Estrai lo ZIP direttamente in `C:\smartmoney-ai`.
3. Conferma la sostituzione dei file.
4. Mantieni nel backend Railway:

```env
RUN_LIVE_POSITION_MONITOR=false
```

5. Esegui:

```powershell
cd C:\smartmoney-ai
Set-ExecutionPolicy -Scope Process Bypass
.\TEST_RISK_HISTORY_CONSOLIDATION.ps1
```

## Risultato atteso

```text
173 passed
e2f9a6b4c731 (head)
11 test Node superati
build frontend completata
```

## Controllo sul sito

Dopo il deploy apri:

```text
Live Trading → Automazione e rischio
```

Premi `Aggiorna stato`. Con lo storico attuale dovresti vedere:

```text
Serie perdite: 3
Cooldown: Libero
```

Il cooldown è libero perché le tre chiusure sono precedenti alla finestra configurata. Nella scheda `Posizioni` saranno visibili valore corrente, PnL non realizzato e ROI.

Poi premi una volta `Esegui un ciclo ora` mantenendo:

```text
DRY_RUN
Uscite automatiche SPENTE
Monitor runtime disabilitato
```

Il ciclo deve quotare le posizioni senza chiuderle e mostrare il dettaglio di ciascuna.
