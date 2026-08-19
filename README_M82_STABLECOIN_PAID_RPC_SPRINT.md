# M82 — Stablecoin-Hardened Paid RPC Sprint

M82 fixes the Gen4 raw-parser false-positive discovered after M81 and replaces the slow public-RPC deep-qualification path with a guarded Helius paid-RPC sprint.

## Parser hardening

Canonical raw parser version:

`canonical-parser-gen4-raw-balance-delta/4`

Two fail-closed controls are added:

1. A speculative-token event is rejected when the same wallet has a non-zero USDC/USDT quote-asset balance delta in the transaction.
2. A BUY must show at least `MIN_SOL_SPENT_FOR_ROI` (0.001 SOL) of material SOL/WSOL input after network fee removal.

The M81 regression transaction that created the false +1853 SOL simulated trade is now rejected as:

`GEN4_COPYABILITY_RAW_NON_SOL_QUOTE_ASSET_DELTA`

## Paid RPC sprint

M82 uses Helius `getTransactionsForAddress` with `transactionDetails=full`.

Hard contracts:

- provider credit accounting: 50 credits per network attempt;
- package hard cap: 9,000 Helius RPC credits;
- production application credit guard remains authoritative;
- actual runtime cap is the minimum of package remaining budget, production total remaining credits, and production RPC remaining credits;
- 8 parallel workers;
- 5-second heartbeat;
- per-request atomic cache and resume;
- no public Solana RPC slow path;
- no Enhanced API discovery tranche;
- no candidate DB writes;
- no raw-capture writes;
- no backend POST;
- no Jupiter;
- no signer;
- no paper/live orders;
- no automatic micro-live authorization.

## Qualification stages

- Discovery: up to 12 deterministic token seeds from M66 + M81 evidence.
- PASS1: up to 50 fresh signer candidates, 100 full transactions each.
- PASS2: up to 8 promising wallets, 400 full transactions each.
- PASS3: up to 4 promising wallets, 1,200 full transactions each.
- Early objective: 2 wallets that pass the unchanged M74 economic gate.

## M81 postmortem

The M81 PASS3 outlier wallet `G4gE...o2vn` was not a valid M74 candidate after strict stablecoin-route exclusion. The diagnostic replay changed its metrics from PF 11768 / +1911 SOL to approximately PF 1.064 / +0.0174 SOL, with the economic gate still failing.

The diagnostic postmortem included with the package is evidence only; the canonical fix is the parser `/3` code plus regression tests.

## Installation safety

The installer:

- requires the exact Git HEAD used by M81;
- verifies the exact current M81 files;
- verifies exact SHA-256 baselines for every existing file M82 modifies;
- verifies exact M66/M79/M80/M81 state artifacts;
- makes a rollback backup before replacing existing files;
- installs atomically;
- runs `py_compile`, the M82 verifier, targeted regression tests, and `git diff --check`;
- executes zero Helius/RPC requests during installation.

No Alembic migration is required.

## Resume safety hotfix — 2026-08-17

The first paid-RPC run exposed two runtime-only defects before any LIVE authorization:

1. concurrent state checkpoints could contend for the same atomic `.tmp` path on Windows;
2. M82's simulation policy overrode legacy M67-M70 `maximum_deep_wallets` and `public_rpc_request_cap` outside their validated contract, causing completed RPC histories to be mislabeled `RPC_RETRY_REQUIRED`.

The resume hotfix serializes checkpoint writes, preserves the canonical M67-M70 economic policy bounds, removes only `RPC_RETRY_REQUIRED` stage rows so they are recomputed, rejects divergent stale `.tmp` state, and reuses the existing per-request Helius cache.  It does not authorize LIVE, signing, paper orders, or candidate database writes.
