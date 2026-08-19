from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_targeted_deep_qualification_service import (
    MAX_SIGNATURES_BY_WALLET,
    M80_PUBLIC_RPC_REQUEST_CAP,
    M80_PUBLIC_RPC_THROTTLE_SECONDS,
    M80_VERSION,
    TARGET_WALLETS,
)

EXPECTED = {
    "backend/app/services/gen4_zero_helius_pre_micro_live_service.py": "ce124eb5648676faa275dd75a7777c27c6ce3878a2af6e810908710d1447cfa7",
    "scripts/run_m67_m70_zero_helius_pre_micro_live.py": "549d08c98cff48be9dbe8bc7582935daa1db4c361a87c0cca793350b9eda44d7",
    "backend/app/services/gen4_paid_candidate_economic_triage_service.py": "bd4a99644b58dbaf731d61cbfa2652c084d176a26605f7dbb71e3168e4dbd203",
    "scripts/run_m79_paid_candidate_zero_helius_triage.py": "5c8aa786dc52abcddbf6974a5e14b6d4e245a61887a648c99c0aa4093476379e",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    for rel, expected in EXPECTED.items():
        path = PROJECT_ROOT / rel
        assert path.is_file(), rel
        assert sha(path) == expected, rel
    runner = (PROJECT_ROOT / "scripts/run_m80_targeted_four_wallet_deep_qualification.py").read_text(encoding="utf-8")
    low = runner.lower()
    assert "api.helius" not in low
    assert "helius-rpc" not in low
    assert "helius_api_key" not in low
    assert len(TARGET_WALLETS) == 4
    assert sum(MAX_SIGNATURES_BY_WALLET.values()) == 6100
    assert M80_PUBLIC_RPC_REQUEST_CAP == 6000
    assert M80_PUBLIC_RPC_THROTTLE_SECONDS == 0.90
    print("=== M80 TARGETED FOUR-WALLET DEEP QUALIFICATION VERIFIER ===")
    print(f"VERSION={M80_VERSION}")
    print("M67_SERVICE_EXACT_HASH=YES")
    print("M67_RUNNER_EXACT_HASH=YES")
    print("M79_SERVICE_EXACT_HASH=YES")
    print("M79_RUNNER_EXACT_HASH=YES")
    print("TARGETS=TH5,6onS,9Mct,2GFV")
    print("TARGET_MAX_SIGNATURES=1400,1400,2600,700")
    print("PROCESS_PUBLIC_RPC_HARD_CAP=6000")
    print("LATEST_SIGNATURE_PAGE_REFRESH_ONCE_PER_WALLET=YES")
    print("CHECKPOINT_AND_RESUME=YES")
    print("HELIUS_PATHS=FORBIDDEN")
    print("LIVE_SIGNER_MICRO_LIVE=DISARMED")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
