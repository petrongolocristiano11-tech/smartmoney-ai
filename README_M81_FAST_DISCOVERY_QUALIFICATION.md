# M81 Fast Discovery + Parallel Economic Qualification

M81 is a manually authorized discovery/qualification lane designed to reduce wall-clock time without changing the canonical Gen4 economic model or M74 thresholds.

- Two diversified M66 Helius discovery lanes, combined hard cap: 86 Enhanced requests / 8600 reserved credits maximum.
- Excludes prior M66/M79/M80 candidates and database inventory.
- Up to 30 new prescreen-pass wallets enter economic triage.
- Public Solana RPC wallet-level parallelism: 3 workers, 0.30s throttle per worker.
- PASS1 60 signatures, PASS2 300 signatures for up to 6, PASS3 1200 signatures only for promising incomplete histories.
- Early stop as soon as at least two wallets fully pass canonical M74 economics.
- Helius discovery is checkpointed so a post-discovery failure does not authorize automatic re-spend.
- No candidate DB writes, no Jupiter, no paper/live orders, no signer, no automatic M75/Micro Live activation.
- RPC retry hardening: partial public-RPC cache is preserved; transient `RPC_RETRY_REQUIRED` stages remain resumable and a rerun after completed discovery does not authorize Helius re-spend.
- Script verifier bootstrap is self-contained when invoked directly from `scripts/`.
