from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(r"C:\smartmoney-ai")
sys.path.insert(0, str(PROJECT))

from backend.app.services.gen4_selective_challenger_lifecycle_bridge_design_service import (
    ACTIVATION_ACTIVE,
    ACTIVATION_DRAINING,
    ACTIVATION_STOPPED,
    M301_BRIDGE_ARMED,
    M301_BRIDGE_IMPLEMENTED,
    M301_LEGACY_ENDPOINT_REQUIRED,
    M301_PROVIDER_MUTATION_REQUIRED,
    OFFICIAL_POSITION_TABLE,
    OFFICIAL_SELECTIVE_SCOPE,
    PROMOTED_ACTIVATION_TABLE,
    PROMOTED_POSITION_TABLE,
    PROMOTED_SELECTIVE_SCOPE,
    build_activation_blueprint,
    build_preparation_report,
    database_blueprint,
    event_is_lifecycle_eligible,
    runtime_blueprint,
    sign_promotion_decision_envelope,
    validate_activation_transition,
    validate_report,
)
from backend.app.services.gen4_selective_challenger_promotion_service import (
    M300_SCOPE,
    M300_VERSION,
    TARGETS,
)


def decision(wallet: str):
    return {
        "scope": M300_SCOPE,
        "version": M300_VERSION,
        "wallet": wallet,
        "state": "PROMOTION_ELIGIBLE_DISARMED",
        "promotion_eligible": True,
        "promotion_armed": False,
        "promotion_executed": False,
        "clean_window": {
            "attempts": 20,
            "accepted": 10,
            "protective_rejects": 10,
            "technical_failures": 0,
            "unmapped_attempts": 0,
        },
        "checks": {"all": True},
        "legacy_endpoint": {
            "compatible": False,
            "reason": "LEGACY_ENDPOINT_REQUIRES_GEN4_COPYABILITY_PASS_AND_RIGID_SELECTION_SNAPSHOT",
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
            "helius_calls": 0,
            "birdeye_cu": 0,
            "jupiter_requests": 0,
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
            "m74_changed": False,
            "m75_changed": False,
            "pam_changed": False,
        },
    }


def policy():
    return {
        "simulated_input_lamports": 10_000_000,
        "slippage_bps": 300,
        "max_quote_latency_ms": 5_000,
        "max_price_impact_bps": 500,
        "max_price_deterioration_bps": 1_000,
        "estimated_network_fee_lamports": 100_000,
        "live_execution": False,
        "paper_execution": False,
        "automatic_live_activation": False,
    }


def main():
    assert M301_BRIDGE_IMPLEMENTED is False
    assert M301_BRIDGE_ARMED is False
    assert M301_PROVIDER_MUTATION_REQUIRED is False
    assert M301_LEGACY_ENDPOINT_REQUIRED is False

    wallet = TARGETS["CGAZ"]
    evaluated = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)
    envelope = sign_promotion_decision_envelope(
        decision(wallet),
        acquisition_report_sha256="a" * 64,
        evaluated_at=evaluated,
    )
    blueprint = build_activation_blueprint(
        envelope,
        operational_policy_snapshot=policy(),
        operational_policy_source_sha256="b" * 64,
        activation_at=evaluated + timedelta(minutes=1),
    )

    assert blueprint["wallet"] == wallet
    assert blueprint["activation_anchor_utc"] > envelope["evaluated_at_utc"]
    assert blueprint["runtime_route"]["helius_provider_union_change_required"] is False
    assert blueprint["runtime_route"]["legacy_start_qualified_candidate_required"] is False
    assert blueprint["runtime_route"]["pre_activation_event_backfill"] is False
    assert blueprint["database_route"]["official_position_table_unchanged"] is True
    assert blueprint["database_route"]["promoted_scope"] == PROMOTED_SELECTIVE_SCOPE
    assert blueprint["formal_claims"]["m298_pass_claimed"] is False

    pre = event_is_lifecycle_eligible(
        blueprint,
        event_received_at=evaluated,
        side="BUY",
        activation_status=ACTIVATION_ACTIVE,
    )
    assert pre["lifecycle_allowed"] is False
    assert pre["reason"] == "PRE_ACTIVATION_EVENT_NO_BACKFILL"

    post_buy = event_is_lifecycle_eligible(
        blueprint,
        event_received_at=evaluated + timedelta(minutes=2),
        side="BUY",
        activation_status=ACTIVATION_ACTIVE,
    )
    assert post_buy["lifecycle_allowed"] is True

    drain_buy = event_is_lifecycle_eligible(
        blueprint,
        event_received_at=evaluated + timedelta(minutes=2),
        side="BUY",
        activation_status=ACTIVATION_DRAINING,
    )
    assert drain_buy["lifecycle_allowed"] is False

    drain_sell = event_is_lifecycle_eligible(
        blueprint,
        event_received_at=evaluated + timedelta(minutes=2),
        side="SELL",
        activation_status=ACTIVATION_DRAINING,
    )
    assert drain_sell["lifecycle_allowed"] is True

    t1 = validate_activation_transition(ACTIVATION_ACTIVE, ACTIVATION_DRAINING, open_positions=3)
    assert t1["allowed"] is True
    t2 = validate_activation_transition(ACTIVATION_DRAINING, ACTIVATION_STOPPED, open_positions=3)
    assert t2["allowed"] is False
    t3 = validate_activation_transition(ACTIVATION_DRAINING, ACTIVATION_STOPPED, open_positions=0)
    assert t3["allowed"] is True

    db = database_blueprint()
    assert db["activation_table"]["name"] == PROMOTED_ACTIVATION_TABLE
    assert db["position_table"]["name"] == PROMOTED_POSITION_TABLE
    assert db["position_table"]["scope_exact"] == PROMOTED_SELECTIVE_SCOPE
    assert db["official_table"]["name"] == OFFICIAL_POSITION_TABLE
    assert db["official_table"]["scope_exact"] == OFFICIAL_SELECTIVE_SCOPE
    assert db["official_table"]["schema_or_check_constraint_change_required"] is False

    runtime = runtime_blueprint()
    assert runtime["no_provider_bridge"]["candidate_separate_wss_reused"] is True
    assert runtime["no_provider_bridge"]["helius_provider_union_mutation"] is False
    assert runtime["isolation"]["official_position_table_touched"] is False

    report = build_preparation_report()
    validate_report(report)
    assert report["architecture"]["state_machine"] == "ACTIVE->DRAINING->STOPPED"
    assert report["readiness_boundary"]["activation_is_not_m298_pass"] is True

    print(
        "M301_PRE_VERIFY=PASS;"
        "design_only=true;"
        "candidate_wss_reused=true;"
        "provider_mutation_required=false;"
        "legacy_endpoint_required=false;"
        "dedicated_activation_table=true;"
        "dedicated_position_table=true;"
        "official_table_unchanged=true;"
        "no_backfill=true;"
        "active_draining_stopped=true;"
        "draining_sell_only=true;"
        "m298_still_required=true"
    )


if __name__ == "__main__":
    main()
