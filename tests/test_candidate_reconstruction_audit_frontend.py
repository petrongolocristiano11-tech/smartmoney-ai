from pathlib import Path


def test_discovery_exposes_max_positions():
    source = Path(
        "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")

    assert "Massimo posizioni aperte" in source
    assert "backtestMaxOpenPositions" in source
    assert (
        "maxOpenPositions: "
        "backtestMaxOpenPositions"
        in source
    )


def test_discovery_exposes_reconstruction_audit():
    source = Path(
        "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")

    assert (
        "Audit ricostruzione + sensibilit?"
        in source
    )
    assert (
        "runCandidateReconstructionAudit"
        in source
    )
    assert "Trade Reconstruction Audit" in source
