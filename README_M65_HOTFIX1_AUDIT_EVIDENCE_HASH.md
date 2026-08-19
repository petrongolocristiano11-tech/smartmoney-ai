# M65 Hotfix1 — hash evidence dei trade ricostruiti

Il report M64 del 14 agosto 2026 ha completato correttamente la raccolta e il
calcolo economico di 83 trade ufficiali più 17 ricostruiti. Il gate M65 lo ha
poi rifiutato perché la funzione di arricchimento `cost_impact` includeva
involontariamente il precedente `evidence_sha256` nel calcolo del digest finale.

Il difetto riguarda esclusivamente 17 hash dei trade ricostruiti e 3 hash della
sensibilità sul batch di chiusura. Gli 83 hash ufficiali, il raw evidence, gli
hash esterni dei due file e tutte le metriche economiche restano invariati.

La correzione:

1. elimina il digest intermedio prima di calcolare l'hash finale del trade;
2. rende visibile il dettaglio di eventuali errori futuri del runner M65;
3. riemette localmente il report già raccolto solo se ogni hash errato coincide
   esattamente con la formula del difetto noto;
4. conserva il report e il raw evidence originali senza sovrascriverli;
5. collega nel nuovo report gli hash e i nomi degli artifact originali;
6. esegue il gate M65 senza rete, Helius, database, backend POST, Jupiter,
   paper, LIVE o signer.

La riammissione del report non trasforma `RECOVERY_ANALYTIC_ONLY` in prova
real-time e non modifica il contatore ufficiale di 83 trade.
