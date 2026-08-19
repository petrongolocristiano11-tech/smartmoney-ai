# M66 — Gen4 Definitive Copyability-Aware Discovery

## Risultato

M66 integra due corsie isolate nello stesso pacchetto:

1. inventario e gate dei wallet già presenti, cached-only e a zero crediti;
2. ricerca manuale di wallet nuovi con Helius Enhanced, con cache SHA-256,
   zero retry e cap hard di sei richieste / 600 crediti.

La vecchia Discovery Helius, il cron, la campagna primaria e il vecchio forward
feed non vengono riattivati o riutilizzati.

La prima corsia stampa separatamente quanti wallet esistono, quanti vengono
scansionati, quanti hanno un backtest completato e quanti possiedono evidenza
position-level completa. Il numero di righe disponibili non viene confuso con
il numero di wallet qualificabili.

### Hotfix cached Trade enrichment

Il report production del 15 agosto ha mostrato 30 wallet ma campi attività,
qualità e backtest tutti non valorizzati. La corsia cached ora legge anche i
record `Trade` già presenti per quei 30 indirizzi, sempre nella stessa
transazione `REPEATABLE READ READ ONLY` e con due query bulk aggiuntive:

- inventario lifetime aggregato per wallet;
- swap degli ultimi sette giorni per attività e qualità.

Attività e qualità vengono ricalcolate soltanto in memoria riutilizzando le
stesse funzioni canoniche dei servizi esistenti. Il report distingue wallet
senza dati locali, wallet che falliscono il pre-screen gratuito e wallet che lo
superano ma richiedono storico mirato. Nessun valore di PnL, profit factor, win
rate o drawdown viene inferito dai semplici record `Trade`; tali metriche
restano mancanti finché non esiste un backtest Gen4 position-level completo.

I nuovi contatori riportano righe Trade lifetime e 7d, wallet coperti dai dati
locali e wallet che superano il pre-screen a zero crediti. Solo questi ultimi
possono entrare nel piano non eseguito di acquisizione storica mirata.

## Gate di ammissione alla canary breve

Un wallet può risultare `QUALIFIED_FOR_SHORT_CANARY` soltanto se supera insieme:

- almeno 100 trade chiusi storici con slippage, fee e copy delay;
- PnL netto positivo e profit factor almeno 1,30;
- almeno 20 chiusure recenti con PnL positivo e PF almeno 1,10;
- drawdown complessivo e recente non superiore al 15%;
- almeno 10 token e concentrazione massima del 25%;
- PnL ancora positivo rimuovendo il trade migliore;
- almeno 4 finestre positive su 5 e PF della peggiore almeno 0,80;
- attività recente sufficiente, senza wallet inattivi o iperattivi;
- qualità `COPIABILE`, dust e size compatibility entro soglia;
- execution coverage almeno 80%, sell matching almeno 90%;
- zero posizioni aperte;
- exitability e compatibilità delle route correnti almeno 80%;
- evidenze cached non scadute;
- modello storico Gen4 esatto: 1,00 SOL di capitale, size fissa 0,05 SOL,
  slippage 100 bps, fee 10 bps, delay 8 secondi con penalità 25 bps/minuto,
  frizione effettiva 103,3333 bps e massimo cinque posizioni simultanee.

La compatibilità Jupiter è dichiarata esplicitamente come route corrente
cached-only: non viene trasformata in una quota storica inventata.

## Classificazioni

- `QUALIFIED_FOR_SHORT_CANARY`: supera il pre-screen; Micro Live resta vietato.
- `NEEDS_TARGETED_HISTORY`: promettente ma campione/storico incompleto.
- `NEEDS_FRESH_COPYABILITY_EVIDENCE`: economia valida, evidenza esecutiva
  scaduta o incompleta.
- `RESEARCH_ONLY`: fallimento economico.
- `BLOCKED`: integrità, qualità, amount o posizioni aperte non conformi.

## Budget e cluster

Il piano pubblico RPC è soltanto un output consigliato e non viene eseguito:
massimo 120 richieste/giorno, 40 per wallet e tre wallet. La selezione della
canary deduplica cluster/copy-chain; due wallet nello stesso cluster non possono
occupare due slot. L'indipendenza deve comunque essere confermata manualmente
prima del futuro consenso multi-wallet.

## Corsia Helius controllata

`RUN_M66_CONTROLLED_HELIUS_DISCOVERY.ps1` richiede la conferma esatta
`SPEND_MAX_600_HELIUS_CREDITS_FOR_M66_DISCOVERY`. Prima della conferma non viene
effettuata alcuna richiesta.

Il budget massimo è:

- una pagina SWAP del seed pubblico;
- massimo due pagine dei token recenti del seed;
- massimo tre pagine dei nuovi wallet candidati;
- 100 crediti stimati per pagina, massimo 600;
- zero retry e nessuna paginazione nascosta.

Il runner esclude tutti i wallet già presenti, deduplica gli indirizzi e salva
fuori dal repository una cache firmata. Le esecuzioni successive riusano
automaticamente la cache valida, quindi una risposta già acquisita costa zero
crediti. La corsia usa il client Helius già contenuto nel repository e la
guardia crediti persistente M63 con `automatic=False`; non abilita l'Enhanced
automatico.

I dati Enhanced di una sola pagina sono un pre-screen attività/copyability, non
una prova economica Gen4: PnL, PF, win rate e drawdown restano `null`. Nessun
wallet nuovo può diventare `QUALIFIED_FOR_SHORT_CANARY` finché non acquisisce
lo storico mirato e non supera il gate cached Gen4 completo.

## Endpoint

`GET /discovered-wallets/definitive-discovery/preview`

L'endpoint legge dati e backtest cached, non persiste run, non esegue POST,
non chiama provider e non applica wallet.

M66 non modifica il frontend e non richiede un build Node: il report completo
viene prodotto dal runner PowerShell fuori dal repository. L'integrazione
visuale potrà essere effettuata soltanto nello step di deploy esplicitamente
autorizzato, senza alterare il motore o le soglie M66.

## Sicurezza

- zero Helius, Jupiter live e public RPC durante la corsia cached;
- zero scritture database e backend POST durante la corsia cached;
- nella corsia Helius, zero scritture candidato/raw capture; le sole scritture
  consentite sono le prenotazioni della guardia crediti M63;
- nessun signer, paper o LIVE;
- nessuna riattivazione cron, campagna primaria o vecchio feed;
- nessuna migrazione Alembic;
- nessuna autorizzazione automatica Micro Live;
- nessun commit, push o deploy eseguito dal pacchetto.

## Esecuzione locale/read-only

Usare `RUN_M66_GEN4_COPYABILITY_AWARE_DISCOVERY.ps1`. Senza snapshot, il wrapper
usa esclusivamente `DATABASE_PUBLIC_URL` in una transazione PostgreSQL
`REPEATABLE READ READ ONLY`; non effettua fallback a `DATABASE_URL`. Gli output
sono salvati fuori dal repository in `Downloads\smartmoney-audits`.

La corsia Helius è separata e non parte durante installazione o test. Per
eseguirla bisogna invocare esplicitamente il relativo wrapper con la conferma;
il wrapper usa il servizio Railway `smartmoney-ai`, verifica chiave, database,
Alembic e budget residuo prima della prima chiamata.
