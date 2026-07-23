from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_exitability_gate_route_precedes_wallet_catch_all():
    source = (ROOT / "backend/app/api/discovered_wallets.py").read_text(encoding="utf-8")
    gate = source.index('"/exitability-gate/refresh"')
    catch_all = source.index('@router.get("/{wallet_address}"')
    assert gate < catch_all
    assert "CandidateExitabilityGateResponse" in source
