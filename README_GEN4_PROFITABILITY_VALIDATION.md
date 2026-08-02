# M47 — Gen4 Walk-Forward Profitability Validation

## Purpose

M47 answers the question “is Gen4 profitable?” without activating paper trading or LIVE.
It uses only already stored database evidence and separates two materially different analyses:

- `STRICT_GEN4`: the closest historically valid replay. A wallet may participate only when a completed candidate backtest existed before the test window, and a token may pass only when a safe token snapshot existed before the signal and was still fresh.
- `SIGNAL_ONLY_PROXY`: a point-in-time training/test proxy. Wallets are selected only from trades before each test window, but token-safety history is bypassed. It can show promising economics, but it cannot prove Gen4 profitability.
- `SIMPLE_COPY_BASELINE`: the same execution and exit assumptions with one qualified source wallet instead of Gen4 consensus.

The service never silently upgrades proxy evidence into strict evidence.

## Walk-forward design

Default windows:

- 14 training days;
- 7 test days;
- 7-day step;
- maximum 4 windows.

For every window, wallet qualification uses only evidence available before the test period. Test signals are built from BUY events after the training cutoff. Future candidate runs and future token-safety snapshots are rejected.

Execution assumptions:

- initial capital: 1 SOL;
- fixed order: 0.005 SOL;
- slippage: 100 bps on entry and exit;
- fee: 10 bps on entry and exit;
- copy delay: 8 seconds;
- maximum entry lag: 180 seconds;
- maximum 5 open positions;
- stop loss: 15%;
- take profit: 30%;
- maximum hold: 240 minutes.

Prices come from recorded source trades. This is explicitly labelled as a source-trade proxy, not a historical market-tick feed.

## Verdicts

- `NOT_EVALUABLE`: strict evidence is insufficient.
- `PROXY_PROMISING_STRICT_EVIDENCE_MISSING`: proxy economics are positive, but strict evidence is insufficient.
- `NEGATIVE_EVIDENCE`: strict sample is evaluable and fails the economic thresholds.
- `PROMISING_NOT_PROVEN`: strict economics pass, but sample size or wallet-profit concentration is not strong enough for proof.
- `PROFITABLE_EVIDENCE`: at least 100 strict closed trades, positive return, profit factor at least 1.30, drawdown at most 25%, at least 60% positive windows, and no wallet above 40% of positive contribution.

A result is evidence, not a guarantee of future returns.

## Database

New Alembic revision:

```text
d2a4b7c0e186 -> e3b5c8d1f297
```

New metadata-only tables:

- `canonical_parser_gen4_profitability_runs`;
- `canonical_parser_gen4_profitability_windows`;
- `canonical_parser_gen4_profitability_trades`.

The GET preview writes no database rows. The POST run is disabled by default and requires the explicit confirmation `RUN_GEN4_PROFITABILITY_VALIDATION`; when enabled later, it writes only these metadata tables.

Downgrade is blocked if persisted M47 runs exist, preventing accidental loss of audit evidence.

## Endpoints

- `GET /integrity/parser-gen4-profitability/status`
- `GET /integrity/parser-gen4-profitability/preview`
- `POST /integrity/parser-gen4-profitability/run`
- `GET /integrity/parser-gen4-profitability/runs/{run_id}`

All endpoints require the existing Automation API Key. The local preview script does not require copying the key because it reads the configured database directly.

## Safety

M47 does not connect to:

- M32 paper execution;
- M35 Micro-LIVE;
- M36 signer or transaction dry-run;
- M46 progressive automation;
- workers, schedulers or streams;
- Helius, Jupiter or any external provider;
- transaction building, signing or submission.

`CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED` remains `false` by default.

## First real result

After installation, the installer creates a report in Downloads:

```text
smartmoney-gen4-profitability-preview-<UTC timestamp>.json
```

The terminal also prints the strict, proxy and baseline metrics. The correct next action depends on that report; thresholds must not be lowered merely to obtain a positive verdict.
