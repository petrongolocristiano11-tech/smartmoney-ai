# M79 — Paid Candidate Zero-Helius Economic Triage

M79 fixes the selection bottleneck revealed by the paid M66 discovery without spending more Helius credits.

## Inputs bound by exact SHA-256

- M66 expanded discovery report: `b2ba27bf...ffc1080`
- M73 qualification report: `adf92b8b...132fea`
- M73 public RPC cache: `c4f3b4e0...740608`

The exact M66/M73 pair contains 27 prescreen-pass candidates, 6 already deep-scanned by M73, and 21 paid candidates still unused.

## Strategy

M79 does **not** re-run M66 and has no Helius path.

1. PASS1: all 21 remaining paid candidates, maximum 60 signatures each.
2. Rank using preliminary Gen4 economics first: closed sample, PnL, PF, win rate, drawdown, recent behavior, PnL without best trade, token diversity/concentration, and RPC completeness.
3. `prescreen_score` is only the final tie-breaker.
4. PASS2: top 8 from PASS1, extended to maximum 150 signatures each using the same cache.
5. Output top 6 for the next deep-history continuation step.

Nominal new public RPC requests are 2,009. The hard cap per process is 2,600, with 0.90 s throttle and at most 4 attempts to absorb public-RPC 429s.

## Safety

- Helius requests: 0
- Helius credits: 0
- M66 re-execution: NO
- DB reads/writes: 0
- Jupiter: 0
- paper orders: 0
- live orders: 0
- signer: disabled
- short canary: not authorized
- Micro Live: not authorized
- official realtime counter remains 83

M79 is only a ranking/triage stage. A strong preliminary result never promotes a wallet by itself.

## Resume behavior

M79 writes a deterministic state file and a delta-only RPC cache. Completed wallets are checkpointed. If public RPC fails, the evidence already collected is preserved; review the failure before any resume.
