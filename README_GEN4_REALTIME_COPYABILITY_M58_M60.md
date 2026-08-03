# SmartMoney AI — M58–M60 Gen4 Real-Time Copyability

## Obiettivo

M58–M60 separa definitivamente due domande che prima erano confuse:

1. **Signal Quality** — i due wallet congelati e la logica Strict producono segnali profittevoli?
2. **Real-Time Copyability** — SmartMoney AI riesce a rilevare quei segnali, ottenere una quotazione realmente disponibile e simulare un ingresso/uscita ancora profittevole dopo ritardo, slippage e costi?

La campagna M52–M57 continua senza essere cancellata. La nuova campagna M58–M60 ha un proprio `anchor_at`, impostato solo dopo che il webhook Helius è stato configurato e verificato online. I 21 giorni della nuova prova non possono essere retrodatati.

## Architettura definitiva

```text
Wallet congelato effettua uno swap confermato
                  |
                  v
Helius Raw Webhook autenticato
                  |
                  v
POST /integrity/parser-gen4-copyability/webhook/helius
                  |
                  v
Persistenza idempotente immediata per firma
                  |
                  v
Worker DB-backed con lease e retry limitati
                  |
                  v
Parser saldo wallet: solo BUY/SELL realmente accoppiati a SOL
                  |
                  v
Jupiter Ultra /order con taker pubblico non firmante
                  |
                  v
Quotazione + costruzione transazione NON FIRMATA
                  |
                  v
Simulazione conservativa e posizione shadow
                  |
                  v
Uscita pro-rata quando lo stesso wallet vende
```

Il polling M56–M57 resta attivo ogni 120 secondi solo per riconciliazione. Un evento visto prima dal polling viene registrato come `RECOVERY_ONLY`, non viene promosso successivamente e non entra mai nelle statistiche di copyability real-time.

## M58 — Helius Raw Webhook Receiver

- endpoint pubblico dedicato, senza `AUTOMATION_API_KEY`;
- autenticazione tramite valore esatto dell'header `Authorization`, confrontato con `secrets.compare_digest`;
- payload massimo 2 MB;
- accetta batch JSON Helius;
- persistenza veloce prima della lavorazione;
- deduplicazione DB su `(campaign_db_id, signature)`;
- duplicate delivery contate senza doppia elaborazione;
- solo i due wallet congelati nella campagna M52–M53;
- Helius configurato con `webhookType=raw`, `transactionTypes=["ANY"]`, `txnStatus=success`, `encoding=jsonParsed`;
- aggiorna automaticamente soltanto il webhook già associato all'endpoint Gen4;
- se esistono webhook non collegati a Gen4, prova prima a creare quello dedicato e non li sovrascrive;
- una sostituzione è possibile solo dopo una conferma esplicita e soltanto se Helius rifiuta la creazione per limiti del piano;
- nessuna chiave o segreto viene stampato nei log dello script di configurazione.
- il payload completo viene hashato, ma nel database viene conservato solo il sottoinsieme replay-completo di firme, account e saldi; log e instruction tree voluminosi vengono rimossi per proteggere il volume Railway da 500 MB.

## M59 — Jupiter Executable Quote Shadow

Per ogni BUY valido:

- misura l'età del segnale usando `blockTime` e l'orario di ricezione;
- ricostruisce la base SOL includendo sia il saldo nativo sia l'eventuale delta di un conto WSOL già esistente, evitando di scartare swap realmente SOL-paired;
- richiede `GET /order` a Jupiter Ultra;
- usa un indirizzo pubblico `taker` generato appositamente, senza conservare alcuna chiave privata;
- pretende che Jupiter restituisca anche una transazione costruita;
- elimina `transaction` e `signedTransaction` prima della persistenza;
- usa `otherAmountThreshold` come output conservativo quando disponibile;
- altrimenti applica l'haircut di slippage congelato;
- misura latenza della quotazione, price impact e deterioramento rispetto al prezzo effettivo stimato del wallet;
- rifiuta segnali vecchi, quotazioni lente, price impact e deterioramento oltre soglia;
- simula un ingresso fisso da 0,01 SOL e una commissione di rete prudenziale.

Per ogni SELL valido:

- individua soltanto posizioni shadow aperte dello stesso wallet e token;
- replica la frazione venduta dal wallet;
- richiede una nuova quotazione Jupiter token→SOL;
- ripartisce output e costi pro-rata;
- chiude la posizione quando il wallet vende tutto o resta solo polvere;
- calcola PnL e rendimento al netto delle commissioni simulate.

Una quotazione Jupiter e una transazione non firmata sono una prova d'eseguibilità molto più realistica del prezzo storico, ma non garantiscono un fill reale. Inoltre il Raw Webhook arriva dopo la conferma della transazione osservata: questa campagna misura quindi la copiabilità reale **post-confirmation**, che è la modalità gratuita e prudente scelta per M58-M60. Per questo il LIVE rimane disabilitato e richiederà successivamente un canary di esecuzione separato; un eventuale percorso pre-confirmation dovrà avere una prova distinta e infrastruttura streaming dedicata.

## M60 — Campagna indipendente e gate LIVE

La nuova campagna congela all'avvio:

- wallet monitorati;
- durata minima: 21 giorni;
- minimo valutabile: 30 trade real-time chiusi;
- prova più solida: 100 trade;
- dimensione simulata: 10.000.000 lamport, cioè 0,01 SOL;
- slippage: 300 bps;
- età massima del segnale: 20.000 ms;
- latenza massima Jupiter: 5.000 ms;
- price impact massimo: 500 bps;
- deterioramento massimo del prezzo: 1.000 bps;
- costo rete stimato: 100.000 lamport per lato;
- copertura webhook minima: 95%;
- profit factor minimo: 1,20;
- drawdown massimo: 20%;
- massimo 3 tentativi di processing per evento.

Il verdetto `PROFITABLE_EVIDENCE` può arrivare soltanto quando sono vere tutte le condizioni della campagna real-time. La campagna Signal Quality rimane necessaria in parallelo. Nessuno dei due risultati abilita automaticamente il LIVE.

## Tabelle nuove

- `canonical_parser_gen4_copyability_campaigns`
- `canonical_parser_gen4_webhook_receipts`
- `canonical_parser_gen4_copyability_positions`
- `canonical_parser_gen4_copyability_worker_states`

La migrazione è `b6f8d2e4c731`, figlia di `a5e7c1d4b926`.

Il downgrade elimina le tabelle soltanto se non esiste evidenza M58–M60. Se sono già arrivati webhook o posizioni, il downgrade si rifiuta per evitare perdita di dati.

## Sicurezza e vincoli non negoziabili

M58–M60 non contiene e non usa:

- chiave privata o seed phrase;
- signer;
- chiamate Jupiter `/execute`;
- invio di transazioni Solana;
- creazione di ordini paper esistenti;
- creazione di ordini LIVE;
- collegamento a permessi LIVE;
- attivazione automatica del LIVE.

Lo stato sicurezza restituisce sempre:

```text
signer_access=false
signed_transactions=0
submitted_transactions=0
paper_orders_created=0
live_orders_created=0
automatic_live_activation=false
```

## Dashboard

La pagina `/gen4-forward` mantiene la campagna Signal Quality e aggiunge il pannello “Real-Time Copyability”. Mostra:

- stato runtime e worker;
- webhook attivo e data del nuovo anchor;
- giorni trascorsi e mancanti;
- webhook, duplicati, recovery-only, elaborati e falliti;
- ingressi eseguibili e rifiutati;
- posizioni aperte e trade chiusi;
- PnL netto, profit factor, win rate e drawdown;
- latenza p50/p95;
- copertura webhook;
- motivi di rifiuto;
- ricevute e posizioni recenti;
- gate mancanti e verdetto.

## Installazione e deploy

Il launcher `INSTALL_TEST_DEPLOY_GEN4_REALTIME_COPYABILITY_M58_M60.ps1`:

**Correzione V2 del passaggio segreti:** il prompt Helius non usa più `Read-Host -AsSecureString`. Il launcher apre una finestra password mascherata compatibile con l’incolla, converte il valore in `SecureString`, usa un BSTR azzerato soltanto in memoria e normalizza con `Trim()`. La chiave viene passata al solo processo Python tramite una variabile d’ambiente figlia di `ProcessStartInfo`, mai tramite command line e mai tramite la variabile d’ambiente del processo PowerShell. Subito dopo `CreateProcess`, il launcher rimuove i segreti dal proprio `ProcessStartInfo` e azzera i riferimenti locali; Python consuma e rimuove immediatamente le variabili dal proprio ambiente.

1. richiede una **nuova** chiave Helius, perché la precedente è comparsa nei log;
2. riusa o richiede la chiave Jupiter;
3. verifica branch `main`, commit baseline `231e6fd6...`, working tree pulita, Docker, Postgres, Railway e campagna M52–M53;
4. crea backup file, dump PostgreSQL locale e dump del database logico Railway;
5. applica i file completi;
6. genera un segreto webhook e un taker pubblico senza chiave privata conservata;
7. aggiorna `.env` senza stampare segreti;
8. esegue compilazione, test mirati, suite completa, build frontend, upgrade/downgrade/upgrade PostgreSQL e verifier OpenAPI;
9. committa localmente solo dopo tutti i test;
10. configura le variabili Railway tramite stdin per i segreti;
11. distribuisce backend e frontend sui servizi esistenti;
12. crea o aggiorna il webhook Helius;
13. verifica campagna, worker, webhook, wallet e guardie di sicurezza;
14. esegue il push e ripete la verifica dopo il redeploy GitHub.

Se un controllo locale fallisce prima del commit, file, `.env` e migrazione vengono ripristinati. Dopo l'attivazione remota del webhook, gli errori attivano una modalità fail-safe: il webhook Gen4 viene disabilitato, runtime e autostart vengono spenti, mentre tabelle ed evidenza restano intatte.

Il rollback post-deploy è intenzionalmente operativo e non elimina il commit o la migrazione quando esiste evidenza: togliere dal codice una revisione Alembic ancora registrata nel database renderebbe i deploy successivi non riproducibili.

## Dopo il deploy

La nuova scadenza dei 21 giorni è quella mostrata nel pannello Real-Time Copyability, non il 23 agosto calcolato per la vecchia campagna. La verifica finale richiede entrambe:

```text
SIGNAL QUALITY: almeno 21 giorni + almeno 30 Strict chiusi
REAL-TIME COPYABILITY: almeno 21 giorni + almeno 30 trade real-time chiusi
```

Se una soglia non è raggiunta, la raccolta continua. Il traguardo preferito resta 100 trade chiusi per ciascuna prova.

**Correzione V3 della regressione frontend M56-M57:** la dashboard usa ora la dicitura esatta `nessun paper / LIVE`, preservando il contratto storico di sicurezza verificato da `tests/test_gen4_forward_feed_frontend_m56_m57.py`. Il test frontend M58-M60 contiene la stessa guardia per impedire future regressioni. Nessuna logica backend, migrazione, campagna, webhook, quotazione o rollback è stata modificata.

**Correzione V4 del roundtrip PostgreSQL:** il preflight risolve la `DATABASE_URL` effettiva con la stessa precedenza ambiente → `.env`, verifica una connessione PostgreSQL reale prima di backup o modifiche e passa la URL esclusivamente nell'ambiente dei processi Alembic e del test di migrazione. Il valore non viene stampato. Lo script di migrazione mantiene inoltre un fallback autonomo al file `.env`, normalizza `postgres://`/`postgresql://` verso `postgresql+psycopg://` e rifiuta SQLite prima di qualsiasi roundtrip.


**Correzione V5 del test PostgreSQL:** il test del resolver usa ora il percorso assoluto derivato da `__file__` per lo script installato nel repository e verifica soltanto il migration harness realmente copiato in `C:\smartmoney-ai`. Non cerca più l’installer di pacchetto nella root del repository, perché quell’installer resta correttamente nella directory temporanea di estrazione. La logica PostgreSQL V4, la migrazione, il launcher sicuro e il rollback sono invariati.



## V6 — Jupiter indipendente dal saldo del wallet shadow

Il percorso M59 reale usa `GET /order` senza `taker` per fissare la quotazione disponibile al momento del rilevamento. Subito dopo usa `GET /build` con il taker pubblico congelato e `mode=fast` per verificare che esistano istruzioni unsigned realmente componibili. Non genera firme, non invia transazioni e non chiama `/execute`.

Il pacchetto include lo stesso precheck non distruttivo già eseguito con successo su Windows. Tale controllo viene ripetuto al punto `[2/16]`, prima di fermare il backend locale, creare backup, applicare file, eseguire suite o migrazioni. Dopo l’installazione dei file, il punto `[11/16]` prova inoltre il percorso runtime effettivo `_quote -> get_quote_and_unsigned_build`.

Le istruzioni raw non vengono salvate nel database: vengono persistiti soltanto esito del build, importi, threshold, impatto, latenza, conteggi delle istruzioni e prova che nessun artefatto firmato o endpoint execute è stato usato.

## V7 — Git whitespace gate definitivo

V7 rimuove l’unico spazio finale presente dopo `return sanitized` nel client Jupiter. La modifica non cambia l’AST Python né il comportamento runtime. Prima di backup o mutazioni, l’installer controlla tutti i file testuali del pacchetto e rifiuta qualsiasi trailing whitespace. I controlli `git diff --check` e `git diff --cached --check` ora acquisiscono e mostrano sempre il percorso e la riga di eventuali problemi.
### Preflight Git sulla baseline reale

Prima del backup, V7 esporta il commit M57 corrente in una directory temporanea, applica lì l’intero payload e le patch alle assertion Alembic, quindi esegue `git diff --check` e `git diff --cached --check` con le impostazioni Git effettive del repository. Il progetto reale non viene toccato se uno dei due controlli non passa.

## V8 — EOF e Git baseline guard definitivo

V8 corregge la riga vuota finale rilevata da Git in `backend/app/main.py` e canonicalizza tutti i file testuali del pacchetto: LF, nessuno spazio finale e una sola newline conclusiva. Il controllo avviene prima di backup o mutazioni sulla copia esatta del commit M57; dopo la copia nel repository reale, `git diff --check` viene ripetuto immediatamente prima dei test lunghi.
