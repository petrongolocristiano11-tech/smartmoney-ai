from pathlib import Path


def read_discovery_source() -> str:
    return Path(
        "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")


def test_discovery_exposes_max_positions():
    source = read_discovery_source()

    assert "Massimo posizioni aperte" in source
    assert "backtestMaxOpenPositions" in source
    assert (
        "maxOpenPositions: "
        "backtestMaxOpenPositions"
        in source
    )


def test_discovery_exposes_reconstruction_audit():
    source = read_discovery_source()

    assert (
        "Audit ricostruzione + sensibilita"
        in source
    )
    assert (
        "runCandidateReconstructionAudit"
        in source
    )
    assert "Trade Reconstruction Audit" in source