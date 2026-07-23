from pathlib import Path


ALLOWED_EXPRESSION = (
    '["COPIABILE", "OSSERVAZIONE"].includes('
    "wallet.quality_classification)"
)


def test_backend_allows_observation_candidates():
    source = Path(
        "backend/app/services/candidate_history_service.py"
    ).read_text(encoding="utf-8")

    assert (
        "allowed_history_quality_classifications"
        in source
    )
    assert '"COPIABILE"' in source
    assert '"OSSERVAZIONE"' in source
    assert (
        "not in allowed_history_quality_classifications"
        in source
    )


def test_frontend_lists_observation_candidates():
    source = Path(
        "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")

    assert (
        "Wallet candidato COPIABILE / OSSERVAZIONE"
        in source
    )
    assert source.count(ALLOWED_EXPRESSION) >= 3


def test_frontend_enables_observation_button():
    source = Path(
        "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")

    assert f"!{ALLOWED_EXPRESSION}" in source
