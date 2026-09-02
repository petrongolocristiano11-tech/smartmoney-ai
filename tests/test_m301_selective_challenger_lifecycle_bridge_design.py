from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.services.gen4_selective_challenger_lifecycle_bridge_design_service import (
    ACTIVATION_ACTIVE,
    ACTIVATION_DRAINING,
    ACTIVATION_STOPPED,
    M301Error,
    PROMOTED_SELECTIVE_SCOPE,
    build_activation_blueprint,
    database_blueprint,
    event_is_lifecycle_eligible,
    sign_promotion_decision_envelope,
    validate_activation_transition,
)
from backend.app.services.gen4_selective_challenger_promotion_service import (
    M300_SCOPE,
    M300_VERSION,
    TARGETS,
)


def _decision(wallet: str):
    return {
        "scope": M300_SCOPE,
        "version": M300_VERSION,
        "wallet": wallet,
        "promotion_eligible": True,
        "promotion_armed": False,
        "promotion_executed": False,
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


def _policy(**overrides):
    p = {
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
    p.update(overrides)
    return p


def _blueprint():
    wallet = TARGETS["CGAZ"]
    evaluated = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)
    env = sign_promotion_decision_envelope(
        _decision(wallet),
        acquisition_report_sha256="a" * 64,
        evaluated_at=evaluated,
    )
    return build_activation_blueprint(
        env,
        operational_policy_snapshot=_policy(),
        operational_policy_source_sha256="b" * 64,
        activation_at=evaluated + timedelta(minutes=1),
    )


def test_bridge_uses_dedicated_tables_and_never_relaxes_official_scope():
    db = database_blueprint()
    assert db["position_table"]["scope_exact"] == PROMOTED_SELECTIVE_SCOPE
    assert db["official_table"]["scope_exact"] == "OFFICIAL_FASTPATH_SELECTIVE"
    assert db["official_table"]["schema_or_check_constraint_change_required"] is False
    assert db["official_table"]["rows_shared_with_promoted_lane"] is False


def test_activation_never_backfills_pre_activation_candidate_events():
    bp = _blueprint()
    anchor = datetime.fromisoformat(bp["activation_anchor_utc"])
    result = event_is_lifecycle_eligible(
        bp,
        event_received_at=anchor,
        side="BUY",
        activation_status=ACTIVATION_ACTIVE,
    )
    assert result["lifecycle_allowed"] is False
    assert result["prepromotion_backfill"] is False


def test_active_allows_post_anchor_buy_and_sell():
    bp = _blueprint()
    anchor = datetime.fromisoformat(bp["activation_anchor_utc"])
    for side in ("BUY", "SELL"):
        result = event_is_lifecycle_eligible(
            bp,
            event_received_at=anchor + timedelta(seconds=1),
            side=side,
            activation_status=ACTIVATION_ACTIVE,
        )
        assert result["lifecycle_allowed"] is True


def test_draining_blocks_new_buy_but_allows_sell_to_close():
    bp = _blueprint()
    anchor = datetime.fromisoformat(bp["activation_anchor_utc"])
    buy = event_is_lifecycle_eligible(
        bp,
        event_received_at=anchor + timedelta(seconds=1),
        side="BUY",
        activation_status=ACTIVATION_DRAINING,
    )
    sell = event_is_lifecycle_eligible(
        bp,
        event_received_at=anchor + timedelta(seconds=1),
        side="SELL",
        activation_status=ACTIVATION_DRAINING,
    )
    assert buy["lifecycle_allowed"] is False
    assert sell["lifecycle_allowed"] is True


def test_stopped_requires_zero_open_positions():
    assert validate_activation_transition(
        ACTIVATION_DRAINING,
        ACTIVATION_STOPPED,
        open_positions=1,
    )["allowed"] is False
    assert validate_activation_transition(
        ACTIVATION_DRAINING,
        ACTIVATION_STOPPED,
        open_positions=0,
    )["allowed"] is True


def test_stopped_cannot_be_resurrected_by_transition():
    assert validate_activation_transition(
        ACTIVATION_STOPPED,
        ACTIVATION_ACTIVE,
        open_positions=0,
    )["allowed"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_quote_latency_ms", 5001),
        ("max_price_impact_bps", 501),
        ("max_price_deterioration_bps", 1001),
    ],
)
def test_activation_policy_cannot_be_more_permissive_than_m298(field, value):
    wallet = TARGETS["89F3"]
    evaluated = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)
    env = sign_promotion_decision_envelope(
        _decision(wallet),
        acquisition_report_sha256="a" * 64,
        evaluated_at=evaluated,
    )
    with pytest.raises(M301Error):
        build_activation_blueprint(
            env,
            operational_policy_snapshot=_policy(**{field: value}),
            operational_policy_source_sha256="b" * 64,
            activation_at=evaluated + timedelta(minutes=1),
        )


def test_activation_requires_true_m300_eligible_decision():
    wallet = TARGETS["CGAZ"]
    d = _decision(wallet)
    d["promotion_eligible"] = False
    with pytest.raises(M301Error):
        sign_promotion_decision_envelope(
            d,
            acquisition_report_sha256="a" * 64,
            evaluated_at=datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc),
        )


def test_activation_blueprint_never_claims_m298_or_micro_live():
    bp = _blueprint()
    assert bp["formal_claims"]["m298_pass_claimed"] is False
    assert bp["formal_claims"]["micro_live_ready_claimed"] is False
    assert bp["formal_claims"]["micro_live_execution_authorized"] is False
    assert bp["safety"]["bridge_implemented"] is False
    assert bp["safety"]["bridge_armed"] is False
