from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4PromotedSelectiveActivation,
    CanonicalParserGen4PromotedSelectivePosition,
)
from backend.app.services.gen4_post_anchor_selective_evidence_service import (
    build_promoted_wallet_evidence,
)
from backend.app.services.gen4_promoted_selective_lifecycle_service import (
    ACTIVATE_CONFIRMATION,
    DRAIN_CONFIRMATION,
    M299_FORMAL_ACQUISITION_REPORT_SHA256,
    M306_FORMAL_REPORT_SHA256,
    STOP_CONFIRMATION,
    M307Error,
    activate_promoted_selective_lifecycle,
    build_activation_package,
    get_promoted_activation_for_event,
    transition_promoted_selective_lifecycle,
)
from backend.app.services.gen4_selective_challenger_promotion_service import (
    M300_SCOPE,
    M300_VERSION,
)

WALLET = "89f3DSmRiFsAZWQXCQMYPwyEUtxbVeCDP7JEjsXrbWST"


def _decision(wallet: str = WALLET) -> dict:
    return {
        "scope": M300_SCOPE,
        "version": M300_VERSION,
        "wallet": wallet,
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


def _policy() -> dict:
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


def _package(activation_at: datetime) -> dict:
    return build_activation_package(
        m300_decision=_decision(),
        m306_report_sha256=M306_FORMAL_REPORT_SHA256,
        m299_acquisition_report_sha256=M299_FORMAL_ACQUISITION_REPORT_SHA256,
        operational_policy_snapshot=_policy(),
        operational_policy_source_sha256="a" * 64,
        candidate_watchlist_wallets=[WALLET],
        activation_at=activation_at,
    )


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    CanonicalParserGen4PromotedSelectiveActivation.__table__.create(engine)
    CanonicalParserGen4PromotedSelectivePosition.__table__.create(engine)
    with Session(engine) as session:
        yield session



def test_m307_extends_the_existing_single_alembic_head():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    assert len(heads) == 1
    revision = scripts.get_revision("f5d8b1c3e470")
    assert revision.down_revision == "e4c7a9d1b268"
    assert "f5d8b1c3e470" in {item.revision for item in scripts.walk_revisions()}


def test_activation_is_explicit_disarmed_and_no_backfill(db: Session):
    activation_at = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    package = _package(activation_at)
    result = activate_promoted_selective_lifecycle(
        db,
        confirmation=ACTIVATE_CONFIRMATION,
        activation_package=package,
    )
    assert result["status"] == "ACTIVE"
    assert result["wallet_address"] == WALLET
    assert result["micro_live_ready_claimed"] is False
    assert result["live_execution_authorized"] is False

    assert get_promoted_activation_for_event(
        db,
        wallet=WALLET,
        event_received_at=activation_at,
        side="BUY",
    ) is None
    active = get_promoted_activation_for_event(
        db,
        wallet=WALLET,
        event_received_at=activation_at + timedelta(microseconds=1),
        side="BUY",
    )
    assert active is not None
    assert active.activation_id == result["activation_id"]

    with pytest.raises(M307Error):
        activate_promoted_selective_lifecycle(
            db,
            confirmation=ACTIVATE_CONFIRMATION,
            activation_package=package,
        )


def test_draining_blocks_buys_allows_sells_and_stop_requires_zero_open(db: Session):
    activation_at = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    activated = activate_promoted_selective_lifecycle(
        db,
        confirmation=ACTIVATE_CONFIRMATION,
        activation_package=_package(activation_at),
    )
    activation = db.query(CanonicalParserGen4PromotedSelectiveActivation).filter_by(
        activation_id=activated["activation_id"]
    ).one()
    position = CanonicalParserGen4PromotedSelectivePosition(
        position_id="p" * 36,
        scope="PROMOTED_CANDIDATE_FASTPATH_SELECTIVE",
        activation_db_id=activation.id,
        activation_id=activation.activation_id,
        entry_fast_event_id="e" * 36,
        status="OPEN",
        wallet_address=WALLET,
        token_mint="T" * 44,
        token_decimals=6,
        entry_signature="S" * 88,
        entry_source="PROCESSED_WSS_PROMOTED_CANDIDATE",
        entry_received_at=activation_at + timedelta(seconds=1),
        opened_at=activation_at + timedelta(seconds=2),
        closed_at=None,
        entry_quote_latency_ms=500,
        entry_price_deterioration_bps=100.0,
        entry_price_impact_bps=10.0,
        entry_transaction_built=True,
        entry_input_lamports=10_000_000,
        entry_output_token_raw=1_000_000,
        remaining_token_raw=1_000_000,
        allocated_entry_fee_lamports=100_000,
        realized_output_lamports=0,
        allocated_exit_fee_lamports=0,
        pnl_lamports=None,
        return_percent=None,
        last_exit_signature=None,
        exit_quote_latency_ms=None,
        exit_price_impact_bps=None,
        exit_transaction_built=False,
        exit_copyable=False,
        close_reason=None,
        entry_quote={},
        exit_quotes=[],
        evidence={},
    )
    db.add(position)
    db.flush()

    drained = transition_promoted_selective_lifecycle(
        db,
        activation_id=activation.activation_id,
        next_status="DRAINING",
        confirmation=DRAIN_CONFIRMATION,
        observed_at=activation_at + timedelta(minutes=1),
    )
    assert drained["status"] == "DRAINING"
    assert get_promoted_activation_for_event(
        db,
        wallet=WALLET,
        event_received_at=activation_at + timedelta(minutes=2),
        side="BUY",
    ) is None
    assert get_promoted_activation_for_event(
        db,
        wallet=WALLET,
        event_received_at=activation_at + timedelta(minutes=2),
        side="SELL",
    ) is not None

    with pytest.raises(M307Error):
        transition_promoted_selective_lifecycle(
            db,
            activation_id=activation.activation_id,
            next_status="STOPPED",
            confirmation=STOP_CONFIRMATION,
        )

    position.status = "CLOSED"
    position.remaining_token_raw = 0
    position.closed_at = activation_at + timedelta(minutes=3)
    position.exit_copyable = True
    position.pnl_lamports = 1000
    db.flush()
    stopped = transition_promoted_selective_lifecycle(
        db,
        activation_id=activation.activation_id,
        next_status="STOPPED",
        confirmation=STOP_CONFIRMATION,
        observed_at=activation_at + timedelta(minutes=4),
    )
    assert stopped["status"] == "STOPPED"
    assert get_promoted_activation_for_event(
        db,
        wallet=WALLET,
        event_received_at=activation_at + timedelta(minutes=5),
        side="SELL",
    ) is None


def test_promoted_m299_adapter_is_full_lifecycle_but_webhook_coverage_fail_closed():
    anchor = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    activation = {
        "activation_id": "a" * 36,
        "activation_anchor_at": anchor,
        "policy_snapshot": _policy(),
    }
    events = []
    for i in range(20):
        when = anchor + timedelta(minutes=30 + i * 20)
        events.append(
            {
                "signature": f"SIG{i}",
                "wallet_address": WALLET,
                "side": "BUY",
                "fast_received_at": when,
                "fast_quote_received_at": when + timedelta(milliseconds=500),
                "fast_prequote_ms": 20,
                "fast_quote_latency_ms": 480,
                "fast_end_to_quote_ms": None,
                "fast_price_deterioration_bps": 100.0,
                "fast_price_impact_bps": 10.0,
                "fast_transaction_built": True,
                "fast_provisional_copyable": True,
                "fast_provisional_rejection_reason": None,
                "parse_error_code": None,
                "quote_error_code": None,
                "evidence": {
                    "promoted_selective_lifecycle": {
                        "entry_eligible": True,
                        "policy_violation": False,
                    }
                },
            }
        )
    positions = []
    for i in range(10):
        positions.append(
            {
                "activation_id": "a" * 36,
                "scope": "PROMOTED_CANDIDATE_FASTPATH_SELECTIVE",
                "wallet_address": WALLET,
                "entry_signature": f"SIG{i}",
                "entry_received_at": events[i]["fast_received_at"],
                "status": "CLOSED",
                "remaining_token_raw": 0,
                "entry_input_lamports": 10_000_000,
                "allocated_entry_fee_lamports": 100_000,
                "pnl_lamports": 1_000_000,
                "exit_copyable": True,
                "closed_at": events[i]["fast_received_at"] + timedelta(minutes=5),
                "evidence": {"exit_failures": []},
            }
        )
    result = build_promoted_wallet_evidence(
        wallet=WALLET,
        events=events,
        positions=positions,
        activation=activation,
        terminal_at=anchor + timedelta(hours=25),
    )
    row = result["wallet_evidence"]
    evaluation = result["m298_individual_evaluation"]
    assert row["entry_attempts"] == 20
    assert row["accepted_attempts"] == 20
    assert row["closed_trades"] == 10
    assert row["webhook_coverage_percent"] == 0.0
    assert row["m299_metadata"]["delivery_coverage_contract"][
        "no_wss_as_webhook_relabeling"
    ] is True
    assert evaluation["checks"]["webhook_coverage"] is False
    assert evaluation["passed"] is False
    assert result["coverage_blocker"] == (
        "INDEPENDENT_WEBHOOK_OR_EQUIVALENT_DELIVERY_COVERAGE_NOT_YET_PROVEN"
    )


def test_activation_package_rejects_wrong_formal_lineage():
    activation_at = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    with pytest.raises(M307Error):
        build_activation_package(
            m300_decision=_decision(),
            m306_report_sha256="0" * 64,
            m299_acquisition_report_sha256=M299_FORMAL_ACQUISITION_REPORT_SHA256,
            operational_policy_snapshot=_policy(),
            operational_policy_source_sha256="a" * 64,
            candidate_watchlist_wallets=[WALLET],
            activation_at=activation_at,
        )
