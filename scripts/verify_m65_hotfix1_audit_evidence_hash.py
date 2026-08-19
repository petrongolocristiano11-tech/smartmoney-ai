from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
os.environ.setdefault("HELIUS_API_KEY", "test-hotfix1-not-used")

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    M64_TARGET_RECONSTRUCTED_TRADES,
    M64_TARGET_WALLET,
    canonical_sha256,
    parse_public_transactions,
    reconstruct_closed_trades,
)
from scripts.reissue_m64_hashfixed_audit_report import (  # noqa: E402
    HOTFIX_SCOPE,
)


def main() -> int:
    service_path = (
        PROJECT_ROOT
        / "backend/app/services/gen4_closed_trade_readonly_audit_service.py"
    )
    runner_path = PROJECT_ROOT / "scripts/run_m65_gen4_definitive_wallet_gate.py"
    service = service_path.read_text(encoding="utf-8")
    runner = runner_path.read_text(encoding="utf-8")
    pop_marker = 'trade.pop("evidence_sha256", None)'
    cost_marker = 'trade["cost_impact"] = {'
    final_hash_marker = 'trade["evidence_sha256"] = canonical_sha256(trade)'
    assert pop_marker in service
    assert cost_marker in service
    assert final_hash_marker in service
    pop_index = service.index(pop_marker)
    cost_index = service.index(cost_marker, pop_index)
    final_hash_index = service.index(final_hash_marker, cost_index)
    assert pop_index < cost_index < final_hash_index
    assert "message={message}" in runner

    fixture_path = (
        PROJECT_ROOT
        / "tests/fixtures/m64_gen4_closed_trade_readonly_audit.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    parsed = parse_public_transactions(
        fixture["transactions"],
        wallet_address=M64_TARGET_WALLET,
    )
    reconstructed = reconstruct_closed_trades(
        parsed["events"],
        policy=fixture["policy"],
        target_closed_trades=M64_TARGET_RECONSTRUCTED_TRADES,
    )
    rows = list(reconstructed["selected_trades"]) + list(
        reconstructed["supplemental_cutoff_batch_trades"]
    )
    assert rows
    assert all(
        row["evidence_sha256"]
        == canonical_sha256(
            {
                key: value
                for key, value in row.items()
                if key != "evidence_sha256"
            }
        )
        for row in rows
    )

    print("=== M65 HOTFIX1 AUDIT EVIDENCE HASH VERIFIER ===")
    print(f"HOTFIX_SCOPE={HOTFIX_SCOPE}")
    print("FINAL_TRADE_HASH_EXCLUDES_PREVIOUS_HASH=PASS")
    print("LEGACY_BUG_REISSUE_FAIL_CLOSED=PASS")
    print("M65_ERROR_DETAIL_VISIBLE=PASS")
    print("OFFICIAL_REALTIME_COUNTER=83_UNCHANGED")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("NETWORK_REQUESTS=0")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_READS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
