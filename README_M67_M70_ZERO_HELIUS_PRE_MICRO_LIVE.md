# M67-M70 — Zero-Helius Pre-Micro-Live Foundation

## Obiettivo

Questo step prepara in un solo percorso read-only le fondamenta concordate dopo
M66, senza acquistare o consumare crediti Helius:

1. M67 unifica l'inventario locale M58-M66 con i report esterni M64 e M65;
2. M68 usa il solo RPC Solana pubblico per misurare attività e, per massimo tre
   candidati, ricostruire lo storico con il parser canonico Gen4;
3. M69 ricalcola il modello economico e prepara il consenso multi-wallet;
4. M70 produce il contratto della short canary e della futura Micro Live, ma li
   lascia esplicitamente disarmati.

Non e un'autorizzazione al trading. Il signer resta assente, LIVE e paper sono
zero e nessun wallet viene applicato automaticamente.

## Fonti e separazione delle prove

Il runner apre PostgreSQL in `REPEATABLE READ READ ONLY`, verifica database e
Alembic head, poi integra:

- wallet e dati cached M66;
- campagne, posizioni e ricevute copyability M58-M61;
- report M64 83+17, se presente e con hash interno valido;
- gate M65, se presente e con hash interno valido;
- attività e transazioni dal RPC pubblico Solana.

Le 83 chiusure real-time ufficiali non vengono mutate. I 17 trade ricostruiti
restano evidenza analitica separata. `RECOVERY_ONLY` non entra nelle metriche
real-time. Il numero di firme pubbliche misura soltanto attività: non viene mai
trasformato in PnL, profit factor, win rate o drawdown.

## Modello Gen4 congelato

La simulazione position-level applica:

- capitale iniziale 1,00 SOL;
- size fissa 0,05 SOL;
- slippage 100 bps;
- commissione 10 bps;
- copy delay 8 secondi;
- penalità 25 bps/minuto, quindi 3,3333 bps per 8 secondi;
- frizione effettiva 103,3333 bps per lato;
- massimo cinque posizioni simultanee;
- pairing causale, partial exit e chiusura solo da eventi pubblici parsati.

Non vengono interrogate quote Jupiter e non vengono inventate quote storiche.

## RPC pubblico, cache e budget

Ogni tentativo di rete, inclusi eventuali retry, consuma una unita del cap hard.
Il default e 600 richieste, massimo tre wallet approfonditi e 150 firme per
wallet. Il runner applica throttling e conserva una cache riutilizzabile con
SHA-256; il wrapper seleziona automaticamente la cache piu recente in
`Downloads\smartmoney-audits`.

Un wallet inattivo o con storico incompleto resta non qualificato. Un errore o
un limite del RPC pubblico produce un fallimento esplicito: non viene sostituito
con dati sintetici.

## Gate economico e consenso

La canary breve richiede almeno 100 trade chiusi, PnL positivo, PF almeno 1,30,
win rate almeno 30%, drawdown massimo 15%, almeno 20 trade recenti con PF almeno
1,10, diversificazione, stabilita e indipendenza dal trade migliore. Le evidenze
esecutive devono inoltre rispettare coverage e matching previsti dalla policy.

Il consenso M69 richiede almeno due wallet di cluster indipendenti sullo stesso
token entro 180 secondi. La logica e riproducibile nel report, ma nessun listener,
cron, campagna primaria o vecchio forward feed viene riattivato.

La short canary preparata richiedera, in uno step futuro autorizzato, almeno 24
ore, 20 tentativi, 10 chiusure, coverage webhook 95%, unsigned build 100%, zero
errori worker e zero violazioni. Anche il superamento di tali soglie non attiva
automaticamente Micro Live.

## Esecuzione

`RUN_M67_M70_ZERO_HELIUS_PRE_MICRO_LIVE.ps1` salva quattro JSON fuori dal repo:
snapshot locale, evidenza RPC, cache RPC e report finale. Se
`DATABASE_PUBLIC_URL` non e presente, usa `railway.cmd run --service Postgres`
solo per fornire la connessione read-only al processo locale.

Il wrapper recupera automaticamente gli ultimi report M64/M65 e la cache M67
dalla cartella di output. La prima esecuzione puo durare per il throttling del
RPC pubblico; le successive riusano le risposte gia validate.

## Contratto di sicurezza

- richieste Helius: zero;
- scritture database: zero;
- backend POST: zero;
- richieste Jupiter: zero;
- paper, LIVE e signer: zero;
- contatore real-time ufficiale: 83 invariato;
- nessuna migrazione Alembic;
- nessuna riattivazione automatica;
- nessun commit, push o deploy eseguito dal pacchetto.
