# SmartMoney AI ? Trade Reconstruction Audit

Audit diagnostico separato dal Promotion Gate.

Include:

- matrice 1, 2 e 5 SOL;
- confronto 5, 10 e 20 posizioni;
- ricostruzione proporzionale delle vendite parziali;
- confronto con e senza bootstrap;
- copertura grezza;
- copertura limitata da capitale e posizioni;
- rendimento senza il miglior trade;
- concentrazione Top 1 e Top 3;
- elenco dei motivi di esclusione;
- massimo posizioni configurabile nella UI.

Sicurezza:

- nessuna richiesta Helius;
- nessuna nuova quota Jupiter;
- nessuna firma o transazione;
- nessuna modifica LIVE;
- nessun worker o stream;
- nessun wallet applicato;
- nessuna generazione creata o resettata;
- Promotion Gate invariato.
