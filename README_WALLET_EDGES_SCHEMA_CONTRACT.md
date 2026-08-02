# Wallet Edges Schema Contract

## Obiettivo

Questa patch corregge lo scostamento strutturale per cui il modello SQLAlchemy
`WalletEdge` e i servizi M31 interrogavano `wallet_edges`, mentre nessuna
migrazione Alembic della catena fino a `c1f3a6b9d075` creava la tabella.

La correzione è esclusivamente strutturale. Non abilita e non modifica:

- M31 automatico;
- M35 Micro-LIVE;
- M36 signer o transaction dry-run;
- M46 progressive automation;
- LIVE trading;
- stream, worker o scheduler;
- firma, submit o invio di transazioni.

## Nuova revisione Alembic

- revisione: `d2a4b7c0e186`;
- revisione precedente: `c1f3a6b9d075`;
- nuova catena: `c1f3a6b9d075 -> d2a4b7c0e186`.

La revisione crea `wallet_edges` con il contratto del modello:

| Colonna | Tipo | Nullable | Default database |
|---|---|---:|---|
| `id` | Integer | no | autoincrement PostgreSQL |
| `source_wallet` | String(64) | no | nessuno |
| `target_wallet` | String(64) | no | nessuno |
| `token_mint` | String(64) | sì | nessuno |
| `edge_type` | String(30) | no | nessuno |
| `strength` | Float | no | nessuno |
| `created_at` | DateTime timezone | no | `now()` |

Indici:

- `ix_wallet_edges_id`;
- `ix_wallet_edges_source_wallet`;
- `ix_wallet_edges_target_wallet`.

Non vengono introdotti unique constraint, check constraint o foreign key non
presenti nel modello.

## Compatibilità con la vecchia tabella runtime

Se Smart Discovery aveva già creato `wallet_edges` tramite il vecchio SQL
runtime, la migrazione:

1. conserva tutte le righe valide;
2. aggiunge eventuali colonne opzionali mancanti;
3. converte `edge_type NULL` in `SHARED_TOKEN`;
4. converte `strength NULL` in `0`;
5. assegna un timestamp alle righe con `created_at NULL`;
6. applica la nullability corretta;
7. rimuove i server default legacy da `edge_type` e `strength`;
8. crea gli indici mancanti.

La migrazione non inventa indirizzi wallet e si interrompe prima di operazioni
distruttive quando trova:

- righe con `source_wallet` o `target_wallet` NULL;
- ID NULL o duplicati;
- valori più lunghi dei limiti del modello;
- colonne, constraint o indici omonimi incompatibili;
- una tabella popolata priva delle colonne fondamentali o della primary key
  prevista.

Una tabella parziale ma vuota può essere ricostruita senza perdita di dati.

## DDL runtime rimosso

`backend/app/services/wallet_graph_engine.py` non esegue più
`CREATE TABLE IF NOT EXISTS` e non effettua più un commit strutturale prima di
ogni salvataggio. Lo schema è ora responsabilità esclusiva di Alembic.

## Downgrade protetto

Il downgrade a `c1f3a6b9d075` elimina `wallet_edges` soltanto quando la tabella è
vuota. Se contiene dati, il downgrade solleva un errore e lascia invariati sia
i dati sia `alembic_version`.

I cicli upgrade/downgrade automatici vengono eseguiti esclusivamente su database
PostgreSQL temporanei creati dal verifier. Il database locale viene soltanto
aggiornato in avanti e poi verificato in modalità read-only.

## File introdotti o sostituiti

- `alembic/versions/d2a4b7c0e186_add_wallet_edges_schema_contract.py`;
- `backend/app/models/wallet_edge.py`;
- `backend/app/services/wallet_graph_engine.py`;
- `tests/test_wallet_edges_schema_contract.py`;
- `scripts/verify_wallet_edges_schema_contract.py`;
- `scripts/test_wallet_edges_postgresql_migration.py`;
- script PowerShell di applicazione, test e rollback;
- documentazione, elenco file e manifest SHA-256.

## Applicazione

Estrarre il pacchetto in una cartella separata e avviare da PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& ".\APPLY_AND_TEST_WALLET_EDGES_SCHEMA_CONTRACT.ps1"
```

Lo script accetta soltanto:

- repository `C:\smartmoney-ai`;
- commit esatto `efc2267e97ac23652cffb8916142a2accd088c73`;
- working tree pulito;
- sorgente e database alla precedente head `c1f3a6b9d075`.

Prima dell'upgrade locale esegue:

- verifica SHA-256 del pacchetto;
- backup dei due file sostituiti;
- compilazione;
- test mirati e regressione M31;
- verifier statico e OpenAPI;
- upgrade pulito su PostgreSQL temporaneo;
- upgrade dalla precedente head;
- downgrade e nuovo upgrade su PostgreSQL temporaneo;
- normalizzazione di una tabella legacy con dati;
- verifica che il downgrade con dati venga bloccato;
- suite backend completa.

Dopo l'upgrade locale verifica revision ID e schema senza effettuare scritture
applicative.

## Vincoli operativi

La patch non esegue commit, push, deploy o modifiche Railway. Non stampa o
richiede private key, seed phrase, Automation API Key, Helius API Key o URL con
credenziali.
