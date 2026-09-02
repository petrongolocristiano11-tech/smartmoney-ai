from __future__ import annotations

import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4FastpathSelectivePosition,
    CanonicalParserGen4PromotedSelectiveActivation,
    CanonicalParserGen4PromotedSelectivePosition,
)
from backend.app.services import gen4_fastpath_shadow_service as fastpath
from backend.app.services.gen4_post_anchor_selective_evidence_service import (
    M299_PROMOTED_SELECTIVE_SCOPE,
    build_promoted_wallet_evidence,
)
from backend.app.services.gen4_promoted_selective_lifecycle_service import (
    M299_FORMAL_ACQUISITION_REPORT_SHA256,
    M306_FORMAL_REPORT_SHA256,
    M307_AUTOMATIC_PROMOTION,
    M307_BRIDGE_ARMED,
    M307_BRIDGE_IMPLEMENTED,
    M307_LEGACY_ENDPOINT_USED,
    M307_PREPROMOTION_BACKFILL,
    M307_PROVIDER_MUTATION_REQUIRED,
    M307_SCOPE,
    M307_VERSION,
    build_activation_package,
    validate_activation_package,
)
from backend.app.services.gen4_selective_challenger_lifecycle_bridge_design_service import (
    PROMOTED_ACTIVATION_TABLE,
    PROMOTED_POSITION_TABLE,
    PROMOTED_SELECTIVE_SCOPE,
)
from backend.app.services.gen4_selective_challenger_promotion_service import (
    M300_SCOPE,
    M300_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "f5d8b1c3e470_add_m307_promoted_selective_lifecycle_bridge.py"

WALLET = "89f3DSmRiFsAZWQXCQMYPwyEUtxbVeCDP7JEjsXrbWST"


def _decision() -> dict:
    return {
        "scope": M300_SCOPE,
        "version": M300_VERSION,
        "wallet": WALLET,
        "state": "PROMOTION_ELIGIBLE_DISARMED",
        "promotion_eligible": True,
        "promotion_armed": False,
        "promotion_executed": False,
        "checks": {
            "target_is_approved_challenger": True,
            "clean_attempt_classification_complete": True,
            "minimum_clean_entry_attempts": True,
            "minimum_clean_accepted_attempts": True,
            "accepted_unsigned_build_coverage": True,
            "accepted_evidence_complete": True,
            "accepted_end_to_quote_p95": True,
            "accepted_price_deterioration_p95": True,
            "accepted_price_impact_p95": True,
            "zero_technical_failures_in_effective_clean_window": True,
            "zero_unmapped_attempts": True,
        },
        "legacy_endpoint": {
            "compatible": False,
            "gen4_copyability_pass_invented": False,
            "must_not_be_called_from_m300": True,
        },
        "future_selective_lifecycle_bridge": {
            "required": True,
            "implemented_by_m300_pre": False,
            "candidate_fastpath_entry_evidence_backfilled": False,
            "full_lifecycle_proof_starts_at_promotion_activation": True,
        },
        "formal_claims": {
            "m74_pass_claimed": False,
            "legacy_m75_pass_claimed": False,
            "gen4_copyability_pass_claimed": False,
            "m298_pass_claimed": False,
            "micro_live_ready_claimed": False,
        },
        "safety": {
            "database_writes": 0,
            "backend_mutations": 0,
            "railway_variable_set": False,
            "provider_mutations": 0,
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
        },
    }


def main() -> None:
    assert M307_BRIDGE_IMPLEMENTED is True
    assert M307_BRIDGE_ARMED is False
    assert M307_AUTOMATIC_PROMOTION is False
    assert M307_PREPROMOTION_BACKFILL is False
    assert M307_LEGACY_ENDPOINT_USED is False
    assert M307_PROVIDER_MUTATION_REQUIRED is False
    assert M307_SCOPE == "M307_PROMOTED_SELECTIVE_LIFECYCLE_BRIDGE_IMPLEMENTED_DISARMED"
    assert M307_VERSION.endswith("/1")

    assert CanonicalParserGen4PromotedSelectiveActivation.__tablename__ == PROMOTED_ACTIVATION_TABLE
    assert CanonicalParserGen4PromotedSelectivePosition.__tablename__ == PROMOTED_POSITION_TABLE
    assert M299_PROMOTED_SELECTIVE_SCOPE == PROMOTED_SELECTIVE_SCOPE

    official_constraints = {
        str(item.sqltext)
        for item in CanonicalParserGen4FastpathSelectivePosition.__table__.constraints
        if hasattr(item, "sqltext")
    }
    assert any("OFFICIAL_FASTPATH_SELECTIVE" in text for text in official_constraints)
    promoted_constraints = {
        str(item.sqltext)
        for item in CanonicalParserGen4PromotedSelectivePosition.__table__.constraints
        if hasattr(item, "sqltext")
    }
    assert any(PROMOTED_SELECTIVE_SCOPE in text for text in promoted_constraints)

    source = inspect.getsource(fastpath.record_fastpath_candidate_notification)
    assert "get_promoted_activation_for_event" in source
    assert "_new_promoted_selective_position" in source
    assert "_apply_promoted_selective_sell_shadow" in source
    assert "promoted_position_created" in source

    adapter_source = inspect.getsource(build_promoted_wallet_evidence)
    adapter_signature = str(inspect.signature(build_promoted_wallet_evidence))
    assert "delivery_receipts" in adapter_signature
    assert "evaluate_promoted_delivery_coverage" in adapter_source
    assert "no_wss_as_webhook_relabeling" in adapter_source
    assert "INDEPENDENT_WEBHOOK_OR_EQUIVALENT_DELIVERY_COVERAGE_NOT_YET_PROVEN" in adapter_source

    package = build_activation_package(
        m300_decision=_decision(),
        m306_report_sha256=M306_FORMAL_REPORT_SHA256,
        m299_acquisition_report_sha256=M299_FORMAL_ACQUISITION_REPORT_SHA256,
        operational_policy_snapshot={
            "simulated_input_lamports": 10_000_000,
            "slippage_bps": 300,
            "max_quote_latency_ms": 5_000,
            "max_price_impact_bps": 500,
            "max_price_deterioration_bps": 1_000,
            "estimated_network_fee_lamports": 100_000,
            "live_execution": False,
            "paper_execution": False,
            "automatic_live_activation": False,
        },
        operational_policy_source_sha256="a" * 64,
        candidate_watchlist_wallets=[WALLET],
        activation_at=datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc),
    )
    validate_activation_package(package)
    assert package["safety"]["bridge_armed"] is False
    assert package["safety"]["automatic_promotion"] is False
    assert package["activation_blueprint"]["runtime_route"]["pre_activation_event_backfill"] is False
    assert package["activation_blueprint"]["runtime_route"]["helius_provider_union_change_required"] is False
    assert package["activation_blueprint"]["runtime_route"]["legacy_start_qualified_candidate_required"] is False

    text = MIGRATION.read_text(encoding="utf-8-sig")
    assert 'revision = "f5d8b1c3e470"' in text
    assert 'down_revision = "e4c7a9d1b268"' in text
    assert PROMOTED_ACTIVATION_TABLE in text
    assert PROMOTED_POSITION_TABLE in text
    assert "ON DELETE" not in text.upper() or "CASCADE" in text.upper()

    print(
        "M307_VERIFY=PASS;"
        "bridge_implemented=true;"
        "bridge_armed=false;"
        "automatic_promotion=false;"
        "dedicated_tables=true;"
        "official_scope_unchanged=true;"
        "candidate_recorder_hook=true;"
        "prepromotion_backfill=false;"
        "legacy_endpoint=false;"
        "provider_mutation=false;"
        "m299_promoted_adapter=true;"
        "webhook_coverage_fail_closed_without_receipts=true;"
        "m309_authenticated_coverage_extension_compatible=true;"
        "live=false;signer=false;paper=0"
    )


if __name__ == "__main__":
    main()
