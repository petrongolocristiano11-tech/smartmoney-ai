from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_contains_candidate_funnel_controls_and_queue():
    api = (
        ROOT / "frontend/src/services/api.js"
    ).read_text(encoding="utf-8")
    page = (
        ROOT / "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")
    assert "refreshCandidateFunnel" in api
    assert "/discovered-wallets/candidate-funnel/refresh" in api
    assert "Discovery Candidate Funnel + Budgeted History Queue" in page
    assert "Candidate Funnel Result" in page
    assert "DISCOVERY_FUNNEL_OPTIONS" in page
    assert "history_queue" in page
    assert "Calcola candidate funnel" in page
    assert "parameters?.resumed" in page
    assert "Cursore iniziale" in page
    assert '"RIPRESA" : "NUOVA"' in page
    assert "ripreso dal cursore salvato" in page


def test_discovery_frontend_has_no_known_mojibake():
    page = (
        ROOT / "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")
    for broken in ("Ã", "Â", "â†", "â€™"):
        assert broken not in page
    assert "Il backfill storico è manuale" in page
    assert "SOL→token→SOL" in page
    assert "Ricalcola qualità DB" in page
    assert "Ricalcola attività DB" in page
