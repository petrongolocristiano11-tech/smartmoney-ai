# M74-M78 — Zero-Helius Final Pre-Micro-Live

Questo pacchetto completa offline il control-plane post-discovery. Non tenta discovery e non contatta alcun provider.

- **M74**: admissione definitiva dei futuri candidati M73 con gli stessi gate economici Gen4.
- **M75**: valutatore Short Real-Time Canary con evidenza SHA-256 fail-closed (24h, 20 tentativi, 10 chiusi, coverage 95%, unsigned 100%, reject <=20%, quote/impact/deterioration P95, zero worker failure/violazioni, zero posizioni aperte e zero failure irrisolti a fine canary).
- **M76**: pool multi-wallet con evidenza SHA-256 fail-closed, conferma manuale di indipendenza, deduplica cluster e consenso sullo stesso token entro 180s; il consenso ignora wallet che non hanno superato M74+M75.
- **M77**: envelope Micro Live che riusa M35 esistente: 0,05 SOL totali, 0,01 SOL/ordine, massimo 3 ordini, 15 minuti; resta disarmato.
- **M78**: gate finale. Puo dichiarare `MICRO_LIVE_READY=YES` solo con almeno due wallet indipendenti che passano M74+M75; non autorizza mai automaticamente l'esecuzione.

## Vincolo assoluto prima del rinnovo Helius

Il codice M74-M78 non importa client HTTP/rete e il verifier rifiuta import `httpx`, `requests`, `urllib`, `socket`, `websockets`, `aiohttp`. L'esecuzione PREPARE legge solo i due JSON M72 gia presenti in `Downloads\smartmoney-audits` e produce un nuovo JSON fuori dal repo.

## Dopo il rinnovo

Non serve sviluppare un nuovo gate: la discovery M73 dovra soltanto produrre candidati reali; gli stessi candidati entrano nel valutatore M74, raccolgono la short canary M75, ricevono conferma indipendenza M76 e vengono valutati da M78. L'ultimo passaggio resta una autorizzazione Micro Live esplicita.

M73/M66 non vengono invocati da questo pacchetto e il lock M73 esistente non viene letto, cancellato o riarmato.

Nessun commit, push o deploy automatico.
