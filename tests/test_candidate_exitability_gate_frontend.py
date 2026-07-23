from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_contains_exitability_gate_controls():
    api = (ROOT / "frontend/src/services/api.js").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/pages/Discovery.jsx").read_text(encoding="utf-8")
    assert "refreshExitabilityGate" in api
    assert "/discovered-wallets/exitability-gate/refresh" in api
    assert "Aggiorna exitability gate" in page
    assert "Batch Exitability Safety Gate" in page
    assert "EXITABILITY_GATE_OPTIONS" in page
