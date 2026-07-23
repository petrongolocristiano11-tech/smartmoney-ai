from pathlib import Path


def test_exit_price_frontend_has_cached_only_workflow():
    api = Path("frontend/src/services/api.js").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/Discovery.jsx").read_text(encoding="utf-8")

    assert "runCandidateExitPriceAudit" in api
    assert "/promotion/exit-price-audit" in api
    assert "Exit Price Provenance &amp; Cached Coverage Audit" in page
    assert "Exit price provenance + cached coverage" in page
    assert "maxLocalPriceAgeHours" in page
    assert "exit_price_coverage_score" in page
    assert "EXIT_PRICE_OPTIONS" in page
    assert "Nessun look-ahead" in page
