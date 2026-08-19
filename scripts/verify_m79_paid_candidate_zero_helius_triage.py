from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_paid_candidate_economic_triage_service import (  # noqa: E402
    M79_EXPECTED_REMAINING,
    M79_EXPECTED_REMAINING_SET_SHA256,
    M79_PASS1_SIGNATURES,
    M79_PASS2_SIGNATURES,
    M79_PASS2_WALLETS,
    M79_PUBLIC_RPC_REQUEST_CAP,
    M79_PUBLIC_RPC_THROTTLE_SECONDS,
    M79_VERSION,
)

EXPECTED_M67_SERVICE_SHA256 = "ce124eb5648676faa275dd75a7777c27c6ce3878a2af6e810908710d1447cfa7"
EXPECTED_M67_RUNNER_SHA256 = "549d08c98cff48be9dbe8bc7582935daa1db4c361a87c0cca793350b9eda44d7"
EXPECTED_CURRENT_M73_RUNNER_SHA256 = "c88b557e2cf6902805e21d8a8c13ac00c18f31ef838c57346729d77ee005ad57"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    m67_service = PROJECT_ROOT / "backend/app/services/gen4_zero_helius_pre_micro_live_service.py"
    m67_runner = PROJECT_ROOT / "scripts/run_m67_m70_zero_helius_pre_micro_live.py"
    m73_runner = PROJECT_ROOT / "scripts/run_m73_controlled_new_wallet_qualification.py"
    m79_runner = PROJECT_ROOT / "scripts/run_m79_paid_candidate_zero_helius_triage.py"

    assert _sha(m67_service) == EXPECTED_M67_SERVICE_SHA256
    assert _sha(m67_runner) == EXPECTED_M67_RUNNER_SHA256
    assert _sha(m73_runner) == EXPECTED_CURRENT_M73_RUNNER_SHA256

    source = m79_runner.read_text(encoding="utf-8")
    lowered = source.lower()
    assert "api.helius" not in lowered
    assert "helius-rpc" not in lowered
    assert "helius_api_key" not in lowered
    assert "get_wallet_history" not in source
    assert 'PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"' in source
    assert "M66_REEXECUTION=NO" in source
    assert "HELIUS_REQUESTS=0" in source
    assert "HELIUS_CREDITS=0" in source
    assert "MICRO_LIVE_EXECUTION_AUTHORIZED=NO" in source

    nominal_requests = (M79_EXPECTED_REMAINING * (1 + M79_PASS1_SIGNATURES)) + (
        M79_PASS2_WALLETS * (1 + (M79_PASS2_SIGNATURES - M79_PASS1_SIGNATURES))
    )
    assert nominal_requests == 2009
    assert nominal_requests < M79_PUBLIC_RPC_REQUEST_CAP == 2600
    assert M79_EXPECTED_REMAINING == 21
    assert M79_PASS2_WALLETS == 8
    assert M79_PASS1_SIGNATURES == 60
    assert M79_PASS2_SIGNATURES == 150
    assert M79_PUBLIC_RPC_THROTTLE_SECONDS == 0.90
    assert len(M79_EXPECTED_REMAINING_SET_SHA256) == 64

    print("=== M79 PAID CANDIDATE ZERO-HELIUS TRIAGE VERIFIER ===")
    print(f"VERSION={M79_VERSION}")
    print("M67_SERVICE_EXACT_HASH=YES")
    print("M67_RUNNER_EXACT_HASH=YES")
    print("CURRENT_M73_RUNNER_EXACT_HASH=YES")
    print("PAID_REMAINING_CANDIDATES=21")
    print("PASS1=21_WALLETS_X_60_SIGNATURES")
    print("PASS2=TOP_8_X_150_SIGNATURES")
    print("NOMINAL_NEW_PUBLIC_RPC_REQUESTS=2009")
    print("PUBLIC_RPC_HARD_CAP_PER_PROCESS=2600")
    print("HELIUS_PATHS=FORBIDDEN")
    print("M66_REEXECUTION=NO")
    print("LIVE_SIGNER_MICRO_LIVE=DISARMED")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
