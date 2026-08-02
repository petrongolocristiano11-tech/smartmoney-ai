# M49-M50 — Gen4 Evidence Sprint

Questo blocco unisce due passaggi senza attivare paper o LIVE:

- **M49 — Companion Wallet Evidence Scout**: parte dai token realmente scambiati dal wallet prioritario, cerca wallet compagni on-chain, misura quanto sono gestibili da recuperare e importa lo storico del candidato migliore in modalità `evidence_only`.
- **M50 — Gen4 Economic Diagnostic**: riesegue M47 subito dopo l'acquisizione e produce il primo risultato economico disponibile per `SIGNAL_ONLY_PROXY` e `SIMPLE_COPY_BASELINE`, insieme alle cause esatte che bloccano wallet o segnali.

## Cosa non fa

- non crea record in `discovered_wallets`;
- non ricalcola qualità, ranking o promozione;
- non modifica il gate `TOO_MANY_OPEN_POSITIONS`;
- non esegue M31;
- non crea paper order;
- non abilita worker, scheduler, stream, signer o LIVE;
- non retrodata o inventa backtest point-in-time.

`STRICT_GEN4` resta forward-only. Lo sprint può mostrare un risultato storico proxy utile, ma non lo presenta come prova strict o autorizzazione al trading reale.

## Budget predefinito

- 3 richieste per scoprire wallet dai token condivisi;
- 8 richieste per sondare l'attività dei candidati;
- 15 richieste per recuperare lo storico di un wallet compagno;
- massimo dichiarato: 26 richieste Helius;
- limite hard nel codice: 40 richieste.

## Selezione del wallet compagno

Lo scout privilegia:

1. più token condivisi con il wallet prioritario;
2. maggiore presenza nelle transazioni dei token seed;
3. una prima pagina di 100 swap che copra almeno 2 giorni, così da evitare wallet iperattivi impossibili da recuperare con un budget ragionevole;
4. eventuale storico locale già sufficiente.

I wallet classificati `SOSPETTO` vengono esclusi prima del probe.

## Risultati possibili

- `PROXY_EVALUABLE_NOT_PROOF`: almeno il campione minimo di trade proxy è disponibile;
- `PROXY_SAMPLE_VISIBLE`: esistono trade proxy, ma il campione è ancora piccolo;
- `QUALIFIED_WALLETS_BUT_NO_CONSENSUS_SIGNALS`: i wallet superano i gate, ma non copiano lo stesso token nella finestra di consenso;
- `WALLET_TRAINING_GATES_NOT_MET`: almeno un gate di training impedisce alla Gen4 di produrre segnali.

Il report include i conteggi dei motivi, ad esempio:

- `TRAINING_OPEN_POSITIONS_ABOVE_MAXIMUM`;
- `TRAINING_RETURN_NOT_POSITIVE`;
- `TRAINING_PROFIT_FACTOR_BELOW_MINIMUM`;
- `TRAINING_CLOSED_POSITIONS_BELOW_MINIMUM`.

## Dati scritti

Durante l'esecuzione reale sono consentiti soltanto:

- trade storici deduplicati;
- metadati del backfill candidato;
- eventuale raw capture già prevista dal client Helius.

Il report JSON viene salvato in `Downloads`.
