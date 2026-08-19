# M87 — Parser token-account rent reclaim hardening

Parser version: `canonical-parser-gen4-raw-balance-delta/4`.

M87 fixes a false SELL classification discovered by the zero-network M86 audit.
When a wallet-owned token account for the candidate mint is closed, Solana can
return its rent-exempt lamports to the wallet. That native inflow is not swap
proceeds. M87 detects closed candidate token accounts via `accountIndex` and
`preBalances -> postBalances == 0`, subtracts the reclaimed lamports from the
SOL-equivalent delta, and fails closed when no real proceeds remain.

The stablecoin route guard from parser v3 remains active. LIVE/signing are not
authorized by this package.

## Resume safety hotfix v2
The M62 AST-isolated verifier must include `_closed_wallet_token_account_reclaim_lamports`
in its `PURE_FUNCTIONS` whitelist. The installer now scans parser AST loaders before any
project write and fails closed if a loader would omit the v4 helper.
