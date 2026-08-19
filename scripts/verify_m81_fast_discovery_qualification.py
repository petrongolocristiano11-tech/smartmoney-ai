from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_fast_discovery_qualification_service import (
    M81_DISCOVERY_CREDIT_CAP_TOTAL,
    M81_DISCOVERY_REQUEST_CAP_TOTAL,
    M81_MAX_TRIAGE_CANDIDATES,
    M81_PASS1_SIGNATURES,
    M81_PASS2_SIGNATURES,
    M81_PASS3_SIGNATURES,
    M81_REQUIRED_QUALIFIED,
    M81_RPC_WORKERS,
    M81_SEEDS,
)


def main() -> int:
    assert M81_DISCOVERY_REQUEST_CAP_TOTAL == 86
    assert M81_DISCOVERY_CREDIT_CAP_TOTAL == 8600
    assert M81_MAX_TRIAGE_CANDIDATES == 30
    assert (M81_PASS1_SIGNATURES, M81_PASS2_SIGNATURES, M81_PASS3_SIGNATURES) == (60, 300, 1200)
    assert M81_RPC_WORKERS == 3
    assert M81_REQUIRED_QUALIFIED == 2
    assert len(M81_SEEDS) == 2 and len(set(M81_SEEDS)) == 2
    address = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    assert all(address.fullmatch(item) for item in M81_SEEDS)

    runner = (PROJECT_ROOT / "scripts/run_m81_fast_discovery_qualification.py").read_text(encoding="utf-8")
    assert "execute_controlled_helius_discovery" in runner
    assert "ThreadPoolExecutor" in runner
    assert "M81_EARLY_STOP_TWO_M74_PASSES=YES" in runner
    assert "LIVE_AUTHORIZED=NO" in runner
    assert "SIGNER_AUTHORIZED=NO" in runner
    assert "MICRO_LIVE_EXECUTION_AUTHORIZED=NO" in runner
    assert "HELIUS_RESPEND_ON_RERUN=NO" in runner
    assert "RPC_RETRY_REQUIRED" in runner
    assert 'state["status"] = "RPC_RETRY_REQUIRED" if retry_required else "COMPLETED"' in runner
    assert "db.add(" not in runner
    assert ".commit(" not in runner
    assert "get_signer(" not in runner
    assert "send_transaction(" not in runner
    assert "execute_live" not in runner.lower()
    print("=== M81 FAST DISCOVERY QUALIFICATION VERIFIER ===")
    print("HELIUS_DISCOVERY_HARD_CAP=86_REQUESTS_8600_CREDITS")
    print("PARALLEL_PUBLIC_RPC_WORKERS=3")
    print("ADAPTIVE_STAGES=60_300_1200")
    print("EARLY_STOP_AFTER_TWO_M74_PASSES=YES")
    print("HELIUS_RESPEND_AFTER_DISCOVERY_CHECKPOINT=NO_AUTOMATIC")
    print("PUBLIC_RPC_RETRY_RESUME=NO_HELIUS_RESPEND")
    print("LIVE_ORDERS=0")
    print("SIGNER_AUTHORIZED=NO")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print("M81_VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
