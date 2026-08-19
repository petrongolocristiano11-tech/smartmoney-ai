# M71 — Continuazione adattiva Zero-Helius

## Risultato atteso

M71 riprende esclusivamente gli output JSON firmati e la cache SHA-256 prodotti
da M67-M70. Non riapre il database e non usa Railway. Continua l'audit pubblico
dei sei wallet che risultavano attivi, scegliendo un batch massimo di quattro:

1. estende fino a 500 firme il wallet `ATXuKM...TdW9`, che mostra eventi BUY e
   SELL ma ha ancora storia position-level incompleta;
2. analizza fino a 300 firme `F2Bn...6qQg`, `2sZak...gZh4` e `5N6i...WXPn`, non
   ancora sottoposti al deep scan;
3. non spende il budget su `4jkL...3qXi`, profilo quasi solo SELL/distribuzione;
4. non spende il budget su `DBqG...9m4h`, resa del parser canonico inferiore al
   10% e nessun trade chiuso ricostruito.

Il piano è deterministico, derivato dal report M67-M70 firmato. Il cap hard è
1800 tentativi RPC pubblici, inclusi i retry, con massimo quattro tentativi e
throttling di 0,75 secondi. La cache precedente viene verificata entry per entry
e riutilizzata; nessuna risposta non verificata viene accettata.

## Correzione del conteggio 83/85

L'audit dei dati reali ha mostrato che il riepilogo locale M67 aveva contato 85
righe `CLOSED`, mentre M64 certifica 83 trade real-time ufficiali e due seed
chiusi in `RECOVERY_GAP_QUARANTINE`. M71 applica il filtro esatto:

`CLOSED + entry WEBHOOK + exit WEBHOOK + entry/exit copyable + PnL presente`.

Le due chiusure in quarantena restano separate e non diventano prova real-time.
La correzione avviene solo su una nuova copia JSON firmata; il database e il
contatore production non vengono modificati.

## Modello economico e fail-closed

La ricostruzione usa invariati capitale 1 SOL, size 0,05 SOL, slippage 100 bps,
commissione 10 bps, delay 8 secondi, penalità 25 bps/minuto, massimo cinque
posizioni e parser canonico Gen4. Nessuna quota Jupiter storica viene inventata.

Un risultato economico ottenuto prima di raggiungere il confine completo della
storia resta `NEEDS_MORE_PUBLIC_RPC_HISTORY`: non può diventare né PASS né FAIL
economico definitivo. La qualifica richiede ancora tutti i gate M67-M70 e almeno
due wallet indipendenti; anche in quel caso la short canary resta solo preparata
e disarmata.

## Output

Il wrapper salva in `Downloads\smartmoney-audits`:

- snapshot locale corretto e firmato;
- evidenza RPC pubblica estesa e firmata;
- report M67-M70 ricalcolato;
- cache RPC aggiornata e firmata;
- report decisionale M71.

Gli input più recenti compatibili vengono scelti automaticamente. Ogni report è
legato agli hash dei propri input; file mescolati, corrotti o incompleti causano
un arresto esplicito.

## Contratto di sicurezza

- richieste Helius: zero;
- letture e scritture database: zero;
- backend POST e Jupiter: zero;
- paper, LIVE, signer e invii: zero;
- contatore ufficiale: 83 invariato;
- `RECOVERY_ONLY`: mai prova real-time;
- Discovery cron, campagna primaria e vecchio forward feed: invariati;
- nessuna migrazione, commit, push o deploy automatico.
