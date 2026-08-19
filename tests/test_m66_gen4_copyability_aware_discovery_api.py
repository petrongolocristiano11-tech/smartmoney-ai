from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_m66_preview_is_get_read_only_and_precedes_wallet_catch_all():
    source = (ROOT / "backend/app/api/discovered_wallets.py").read_text(
        encoding="utf-8"
    )
    route = source.index('"/definitive-discovery/preview"')
    catch_all = source.index('@router.get("/{wallet_address}"')
    assert route < catch_all
    assert '@router.get(\n    "/definitive-discovery/preview"' in source
    assert "build_cached_discovery_snapshot" in source
    assert "evaluate_copyability_aware_discovery" in source
    assert "@router.post" not in source[route - 30 : route]


def test_m66_schema_exposes_decision_and_safety_sections():
    source = (ROOT / "backend/app/schemas/discovered_wallet.py").read_text(
        encoding="utf-8"
    )
    assert "class Gen4CopyabilityAwareDiscoveryPreviewResponse" in source
    for field in (
        "selected_wallets",
        "candidate_results",
        "acquisition_plan",
        "short_canary_contract",
        "multi_wallet_consensus_readiness",
        "activation",
        "safety",
        "integrity",
    ):
        assert field in source
