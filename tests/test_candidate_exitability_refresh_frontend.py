from pathlib import Path


def test_exitability_refresh_frontend_has_bound_cached_workflow():
    page = Path("frontend/src/pages/Discovery.jsx").read_text(
        encoding="utf-8"
    )
    api = Path("frontend/src/services/api.js").read_text(
        encoding="utf-8"
    )

    assert "/promotion/exitability-refresh" in api
    assert "lifecycle_run_id: lifecycleRunId" in api
    assert "refreshCandidateOpenPositionExitability" in page
    assert "Refresh Jupiter posizioni aperte" in page
    assert "Open Position Jupiter Exitability Refresh" in page
    assert "response.data.exit_price_audit" in page
    assert "transactions_signed" not in page
