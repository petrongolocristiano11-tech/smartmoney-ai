from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_candidate_funnel_routes_precede_wallet_catch_all():
    source = (
        ROOT / "backend/app/api/discovered_wallets.py"
    ).read_text(encoding="utf-8")
    refresh_route = source.index('"/candidate-funnel/refresh"')
    latest_route = source.index('"/candidate-funnel/latest"')
    catch_all = source.index('@router.get("/{wallet_address}"')
    assert refresh_route < catch_all
    assert latest_route < catch_all
    assert "CandidateDiscoveryFunnelResponse" in source
    assert "history_request_budget" in source


def test_candidate_funnel_filter_and_sort_are_exposed():
    source = (
        ROOT / "backend/app/api/discovered_wallets.py"
    ).read_text(encoding="utf-8")
    assert "discovery_funnel: Literal" in source
    assert '"NEEDS_LOCAL_DATA"' in source
    assert '"NEEDS_HISTORY"' in source
    assert '"discovery_funnel_score"' in source
    assert '"discovery_funnel_priority"' in source
