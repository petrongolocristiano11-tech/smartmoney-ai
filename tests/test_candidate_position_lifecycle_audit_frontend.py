from pathlib import Path


def test_lifecycle_audit_frontend_is_wired():
    api_source = Path(
        "frontend/src/services/api.js"
    ).read_text(encoding="utf-8")
    page_source = Path(
        "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")

    assert (
        "runCandidatePositionLifecycleAudit"
        in api_source
    )
    assert (
        "/promotion/lifecycle-audit"
        in api_source
    )
    assert (
        "Position lifecycle + stale audit"
        in page_source
    )
    assert (
        "Position Lifecycle &amp; Stale Position Audit"
        in page_source
    )
    assert (
        "lifecycle_summary"
        in page_source
    )
    assert (
        "forced_close_skipped_unquotable"
        in page_source
    )
    assert (
        "Nessuna richiesta Helius/Jupiter"
        in page_source
    )
