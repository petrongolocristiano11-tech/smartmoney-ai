from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401
from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserAssistedMicroLivePilot,
    CanonicalParserLiveIncident,
    CanonicalParserLiveObservabilitySnapshot,
    CanonicalParserProductionCircuitBreaker,
    CanonicalParserProductionCircuitBreakerEvent,
    CanonicalParserProductionHardeningAssessment,
    CanonicalParserProgressiveAutomationLease,
    CanonicalParserProgressiveAutomationLeaseEvent,
)
import backend.app.services.blockchain_parser_progressive_automation_service as service

NOW = datetime(2026, 7, 29, 19, 0, tzinfo=timezone.utc)
WALLET = "1" * 32
OTHER_WALLET = "3" * 32
TOKEN = "2" * 32
OTHER_TOKEN = "4" * 32


def settings_for_m46(**overrides):
    values = {
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_ENABLED": True,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_GUARD_ENABLED": True,
        "CANONICAL_PARSER_PRODUCTION_CIRCUIT_BREAKER_ENABLED": True,
        "CANONICAL_PARSER_PRODUCTION_HARDENING_ASSESSMENT_TTL_MINUTES": 15,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_PILOT_LOOKBACK_DAYS": 30,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MIN_COMPLETED_PILOTS_ASSISTED": 1,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MIN_COMPLETED_PILOTS_SUPERVISED": 3,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MIN_COMPLETED_PILOTS_CANDIDATE": 5,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MAX_VALIDITY_MINUTES": 60,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MAX_BUDGET_SOL": 0.01,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MAX_SUBMISSIONS": 10,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_REQUIRE_HEALTHY_OBSERVABILITY": True,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_REQUIRE_ZERO_ACTIVE_INCIDENTS": True,
        "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_REQUIRE_ZERO_UNCERTAIN_SUBMISSIONS": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def add_healthy_snapshot(db: Session, suffix: str = "a"):
    row = CanonicalParserLiveObservabilitySnapshot(
        snapshot_id=f"m46-snapshot-{suffix}".ljust(36, "0")[:36],
        snapshot_key=(suffix * 64)[:64],
        scope="M43_LIVE_OPERATIONAL_OBSERVABILITY",
        status="HEALTHY",
        uncertain_submission_count=0,
        stale_submission_count=0,
        unsettled_count=0,
        review_position_count=0,
        active_incident_count=0,
        open_alert_count=0,
        reason_codes=[],
        metric_snapshot={"counts": {}},
        policy_snapshot={},
        evidence_hash=((suffix.upper() if suffix.isalpha() else "b") * 64)[:64],
        actor_label="TEST",
        note=None,
        observed_at=NOW,
        expires_at=NOW + timedelta(hours=2),
    )
    db.add(row)
    db.commit()
    return row


def add_completed_pilot(db: Session, index: int = 1, *, status: str = "COMPLETED", wallet: str = WALLET, token: str = TOKEN):
    char = str((index % 9) + 1)
    row = CanonicalParserAssistedMicroLivePilot(
        pilot_id=f"m46-pilot-{index}".ljust(36, "0")[:36],
        pilot_key=char * 64,
        scope="M45_ASSISTED_MICRO_LIVE_PILOT",
        status=status,
        certification_db_id=index,
        certification_id=f"m46-cert-{index}".ljust(36, "0")[:36],
        wallet_address=wallet,
        network="mainnet-beta",
        token_mint=token,
        max_entry_budget_sol=Decimal("0.003"),
        max_total_fee_sol=Decimal("0.001"),
        max_position_duration_minutes=30,
        required_checklist_count=10,
        passed_checklist_count=10,
        entry_submission_id=f"entry-{index}".ljust(36, "0")[:36],
        entry_settlement_id=f"entry-settlement-{index}".ljust(36, "0")[:36],
        position_id=f"position-{index}".ljust(36, "0")[:36],
        exit_intent_id=f"exit-intent-{index}".ljust(36, "0")[:36],
        exit_submission_id=f"exit-{index}".ljust(36, "0")[:36],
        exit_settlement_id=f"exit-settlement-{index}".ljust(36, "0")[:36],
        post_observability_snapshot_id=f"m46-snapshot-a".ljust(36, "0")[:36],
        pilot_snapshot={},
        completion_snapshot={
            "realized_pnl_sol": "0.000100000",
            "total_fee_sol": "0.000100000",
        },
        evidence_hash=(char[::-1] or char) * 64,
        actor_label="TEST",
        note=None,
        issued_at=NOW - timedelta(days=index),
        expires_at=NOW + timedelta(hours=1),
        armed_at=NOW - timedelta(days=index),
        completed_at=NOW - timedelta(days=index - 1) if status == "COMPLETED" else None,
        aborted_at=NOW - timedelta(days=index - 1) if status == "ABORTED" else None,
        latest_event_sequence=1,
        latest_event_hash=char * 64,
    )
    db.add(row)
    db.commit()
    return row


def make_ready_assessment(db: Session, *, stage="ASSISTED", pilots=1, token="m46-assessment-ready"):
    add_healthy_snapshot(db)
    for i in range(1, pilots + 1):
        add_completed_pilot(db, i)
    max_submissions = {"ASSISTED": 2, "SUPERVISED": 6, "AUTOMATION_CANDIDATE": 10}[stage]
    budget = {"ASSISTED": "0.003", "SUPERVISED": "0.0035", "AUTOMATION_CANDIDATE": "0.004"}[stage]
    args = dict(
        wallet_address=WALLET,
        token_mint=TOKEN,
        requested_stage=stage,
        requested_max_budget_sol=budget,
        requested_max_submissions=max_submissions,
        idempotency_token=token,
    )
    preview = service.preview_production_hardening_assessment(
        db, **args, settings_object=settings_for_m46(), evaluated_at=NOW
    )
    assert preview["status"] == "READY"
    return service.assess_production_hardening(
        db,
        **args,
        confirmation=preview["confirmation"],
        settings_object=settings_for_m46(),
        assessed_at=NOW,
    )


def make_lease(db: Session, *, stage="ASSISTED", pilots=1):
    assessment = make_ready_assessment(db, stage=stage, pilots=pilots, token=f"m46-assess-{stage.lower()}")
    preview = service.preview_progressive_automation_lease(
        db,
        assessment_id=assessment["assessment_id"],
        validity_minutes=10,
        idempotency_token=f"m46-lease-{stage.lower()}",
        settings_object=settings_for_m46(),
        evaluated_at=NOW,
    )
    assert preview["status"] == "READY"
    return service.issue_progressive_automation_lease(
        db,
        assessment_id=assessment["assessment_id"],
        validity_minutes=10,
        idempotency_token=f"m46-lease-{stage.lower()}",
        confirmation=preview["confirmation"],
        settings_object=settings_for_m46(),
        issued_at=NOW,
    )


def test_m46_flags_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_ENABLED is False
    assert configured.CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_GUARD_ENABLED is False
    assert configured.CANONICAL_PARSER_PRODUCTION_CIRCUIT_BREAKER_ENABLED is False


def test_m46_models_and_migration_registered():
    for table in (
        "canonical_parser_production_hardening_assessments",
        "canonical_parser_progressive_automation_leases",
        "canonical_parser_progressive_automation_lease_events",
        "canonical_parser_production_circuit_breakers",
        "canonical_parser_production_circuit_breaker_events",
    ):
        assert table in Base.metadata.tables
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("c1f3a6b9d075").down_revision == "b0e2f5a8c964"
    assert scripts.get_heads() == ["c1f3a6b9d075"]


def test_status_is_manual_and_no_dispatch(db):
    status = service.get_progressive_automation_status(db, settings_object=settings_for_m46(), evaluated_at=NOW)
    assert status["safety"]["automatic_dispatch"] is False
    assert status["safety"]["worker_connected"] is False
    assert status["policy"]["manual_trigger_only"] is True


def test_assisted_requires_completed_pilot_evidence(db):
    add_healthy_snapshot(db)
    preview = service.preview_production_hardening_assessment(
        db,
        wallet_address=WALLET,
        token_mint=TOKEN,
        requested_stage="ASSISTED",
        requested_max_budget_sol="0.003",
        requested_max_submissions=2,
        idempotency_token="m46-no-pilot",
        settings_object=settings_for_m46(),
        evaluated_at=NOW,
    )
    assert preview["status"] == "INSUFFICIENT_DATA"
    assert "M46_COMPLETED_PILOT_EVIDENCE_INSUFFICIENT" in preview["reason_codes"]


def test_observe_only_ready_without_pilot_but_cannot_submit(db):
    add_healthy_snapshot(db)
    preview = service.preview_production_hardening_assessment(
        db,
        wallet_address=WALLET,
        token_mint=TOKEN,
        requested_stage="OBSERVE_ONLY",
        requested_max_budget_sol="0",
        requested_max_submissions=0,
        idempotency_token="m46-observe-only",
        settings_object=settings_for_m46(),
        evaluated_at=NOW,
    )
    assert preview["status"] == "READY"
    assert preview["eligible_stage"] == "OBSERVE_ONLY"


def test_one_completed_pilot_enables_assisted(db):
    assessment = make_ready_assessment(db)
    assert assessment["eligible_stage"] == "ASSISTED"
    assert assessment["completed_pilot_count"] == 1
    assert assessment["status"] == "READY"


def test_supervised_requires_three_completed_pilots(db):
    add_healthy_snapshot(db)
    add_completed_pilot(db, 1)
    preview = service.preview_production_hardening_assessment(
        db,
        wallet_address=WALLET,
        token_mint=TOKEN,
        requested_stage="SUPERVISED",
        requested_max_budget_sol="0.003",
        requested_max_submissions=6,
        idempotency_token="m46-supervised-insufficient",
        settings_object=settings_for_m46(),
        evaluated_at=NOW,
    )
    assert preview["status"] == "INSUFFICIENT_DATA"
    assert preview["eligible_stage"] == "ASSISTED"


def test_three_completed_pilots_enable_supervised(db):
    assessment = make_ready_assessment(db, stage="SUPERVISED", pilots=3, token="m46-supervised-ready")
    assert assessment["eligible_stage"] == "SUPERVISED"
    assert assessment["recommended_max_submissions"] == 6


def test_aborted_pilot_blocks_promotion(db):
    add_healthy_snapshot(db)
    add_completed_pilot(db, 1)
    add_completed_pilot(db, 2, status="ABORTED")
    preview = service.preview_production_hardening_assessment(
        db,
        wallet_address=WALLET,
        token_mint=TOKEN,
        requested_stage="ASSISTED",
        requested_max_budget_sol="0.003",
        requested_max_submissions=2,
        idempotency_token="m46-aborted-block",
        settings_object=settings_for_m46(),
        evaluated_at=NOW,
    )
    assert preview["status"] == "BLOCKED"
    assert "M46_ABORTED_PILOT_PRESENT" in preview["reason_codes"]


def test_unhealthy_observability_blocks_assessment(db):
    add_completed_pilot(db, 1)
    preview = service.preview_production_hardening_assessment(
        db,
        wallet_address=WALLET,
        token_mint=TOKEN,
        requested_stage="ASSISTED",
        requested_max_budget_sol="0.003",
        requested_max_submissions=2,
        idempotency_token="m46-no-health",
        settings_object=settings_for_m46(),
        evaluated_at=NOW,
    )
    assert preview["status"] == "BLOCKED"
    assert "M46_OPERATIONAL_HEALTH_NOT_READY" in preview["reason_codes"]


def test_assessment_requires_enabled_flag(db):
    add_healthy_snapshot(db)
    add_completed_pilot(db, 1)
    args = dict(
        wallet_address=WALLET,
        token_mint=TOKEN,
        requested_stage="ASSISTED",
        requested_max_budget_sol="0.003",
        requested_max_submissions=2,
        idempotency_token="m46-disabled",
    )
    preview = service.preview_production_hardening_assessment(db, **args, settings_object=settings_for_m46(), evaluated_at=NOW)
    with pytest.raises(service.CanonicalParserProgressiveAutomationError) as exc:
        service.assess_production_hardening(
            db,
            **args,
            confirmation=preview["confirmation"],
            settings_object=settings_for_m46(CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_ENABLED=False),
            assessed_at=NOW,
        )
    assert exc.value.code == "M46_DISABLED"


def test_assessment_is_idempotent(db):
    first = make_ready_assessment(db)
    preview = service.preview_production_hardening_assessment(
        db,
        wallet_address=WALLET,
        token_mint=TOKEN,
        requested_stage="ASSISTED",
        requested_max_budget_sol="0.003",
        requested_max_submissions=2,
        idempotency_token="m46-assessment-ready",
        settings_object=settings_for_m46(),
        evaluated_at=NOW,
    )
    second = service.assess_production_hardening(
        db,
        wallet_address=WALLET,
        token_mint=TOKEN,
        requested_stage="ASSISTED",
        requested_max_budget_sol="0.003",
        requested_max_submissions=2,
        idempotency_token="m46-assessment-ready",
        confirmation=preview["confirmation"],
        settings_object=settings_for_m46(),
        assessed_at=NOW,
    )
    assert second["assessment_id"] == first["assessment_id"]
    assert db.query(CanonicalParserProductionHardeningAssessment).count() == 1


def test_issue_lease_persists_initial_event(db):
    lease = make_lease(db)
    assert lease["status"] == "ACTIVE"
    assert lease["automatic_dispatch_permitted"] is False
    assert db.query(CanonicalParserProgressiveAutomationLease).count() == 1
    assert db.query(CanonicalParserProgressiveAutomationLeaseEvent).count() == 1


def test_guard_off_is_non_intrusive(db):
    result = service.validate_progressive_automation_lease_for_submission(
        db,
        lease_id=None,
        side="BUY",
        token_mint=TOKEN,
        requested_budget_sol="0.003",
        wallet_address=WALLET,
        assisted_micro_live_pilot_id=None,
        settings_object=settings_for_m46(CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_GUARD_ENABLED=False),
        evaluated_at=NOW,
    )
    assert result["required"] is False
    assert result["ready"] is True


def test_assisted_lease_requires_m45_pilot_on_submission(db):
    lease = make_lease(db)
    blocked = service.validate_progressive_automation_lease_for_submission(
        db,
        lease_id=lease["lease_id"],
        side="BUY",
        token_mint=TOKEN,
        requested_budget_sol="0.003",
        wallet_address=WALLET,
        assisted_micro_live_pilot_id=None,
        settings_object=settings_for_m46(),
        evaluated_at=NOW,
    )
    assert blocked["ready"] is False
    assert "M46_ASSISTED_STAGE_REQUIRES_M45_PILOT" in blocked["reason_codes"]
    ready = service.validate_progressive_automation_lease_for_submission(
        db,
        lease_id=lease["lease_id"],
        side="BUY",
        token_mint=TOKEN,
        requested_budget_sol="0.003",
        wallet_address=WALLET,
        assisted_micro_live_pilot_id="pilot-present",
        settings_object=settings_for_m46(),
        evaluated_at=NOW,
    )
    assert ready["ready"] is True


def test_lease_is_wallet_token_and_budget_bound(db):
    lease = make_lease(db)
    result = service.validate_progressive_automation_lease_for_submission(
        db,
        lease_id=lease["lease_id"],
        side="BUY",
        token_mint=OTHER_TOKEN,
        requested_budget_sol="0.004",
        wallet_address=OTHER_WALLET,
        assisted_micro_live_pilot_id="pilot-present",
        settings_object=settings_for_m46(),
        evaluated_at=NOW,
    )
    assert "M46_PROGRESSIVE_AUTOMATION_WALLET_MISMATCH" in result["reason_codes"]
    assert "M46_PROGRESSIVE_AUTOMATION_TOKEN_MISMATCH" in result["reason_codes"]
    assert "M46_PROGRESSIVE_AUTOMATION_BUDGET_EXCEEDED" in result["reason_codes"]


def test_lease_submission_slots_are_bounded_and_exhausted(db):
    lease = make_lease(db)
    for index in (1, 2):
        result = service.consume_progressive_automation_lease_submission_slot(
            db,
            lease_id=lease["lease_id"],
            submission_id=f"submission-{index}",
            side="BUY" if index == 1 else "SELL",
            token_mint=TOKEN,
            requested_budget_sol="0.003" if index == 1 else "0",
            wallet_address=WALLET,
            assisted_micro_live_pilot_id="pilot-present",
            settings_object=settings_for_m46(),
            consumed_at=NOW + timedelta(seconds=index),
        )
    assert result["status"] == "EXHAUSTED"
    assert result["used_submission_count"] == 2
    assert db.query(CanonicalParserProgressiveAutomationLeaseEvent).count() == 3

    duplicate = service.consume_progressive_automation_lease_submission_slot(
        db,
        lease_id=lease["lease_id"],
        submission_id="submission-2",
        side="SELL",
        token_mint=TOKEN,
        requested_budget_sol="0",
        wallet_address=WALLET,
        assisted_micro_live_pilot_id="pilot-present",
        settings_object=settings_for_m46(),
        consumed_at=NOW + timedelta(seconds=3),
    )
    assert duplicate["status"] == "EXHAUSTED"
    assert duplicate["used_submission_count"] == 2
    assert db.query(CanonicalParserProgressiveAutomationLeaseEvent).count() == 3

    with pytest.raises(service.CanonicalParserProgressiveAutomationError):
        service.consume_progressive_automation_lease_submission_slot(
            db,
            lease_id=lease["lease_id"],
            submission_id="submission-3",
            side="BUY",
            token_mint=TOKEN,
            requested_budget_sol="0.001",
            wallet_address=WALLET,
            assisted_micro_live_pilot_id="pilot-present",
            settings_object=settings_for_m46(),
            consumed_at=NOW + timedelta(seconds=3),
        )


def test_revoke_lease_is_fail_closed(db):
    lease = make_lease(db)
    row = db.scalar(select(CanonicalParserProgressiveAutomationLease))
    confirmation = f"{service.REVOKE_PREFIX}:{row.lease_id}:{row.evidence_hash}"
    result = service.revoke_progressive_automation_lease(
        db,
        lease_id=row.lease_id,
        reason="manual revoke",
        confirmation=confirmation,
        settings_object=settings_for_m46(),
        revoked_at=NOW + timedelta(minutes=1),
    )
    assert result["status"] == "REVOKED"


def test_trip_breaker_trips_active_lease(db):
    lease = make_lease(db)
    preview = service.preview_trip_production_circuit_breaker(
        db,
        wallet_address=WALLET,
        reason_codes=["RPC_ERROR_RATE"],
        source_type="OBSERVABILITY",
        source_id="snapshot-1",
        idempotency_token="m46-trip-breaker",
        evaluated_at=NOW + timedelta(minutes=1),
    )
    breaker = service.trip_production_circuit_breaker(
        db,
        wallet_address=WALLET,
        reason_codes=["RPC_ERROR_RATE"],
        source_type="OBSERVABILITY",
        source_id="snapshot-1",
        idempotency_token="m46-trip-breaker",
        confirmation=preview["confirmation"],
        settings_object=settings_for_m46(),
        tripped_at=NOW + timedelta(minutes=1),
    )
    assert breaker["status"] == "TRIPPED"
    row = db.scalar(select(CanonicalParserProgressiveAutomationLease).where(CanonicalParserProgressiveAutomationLease.lease_id == lease["lease_id"]))
    assert row.status == "TRIPPED"
    assert db.query(CanonicalParserProductionCircuitBreakerEvent).count() == 1


def test_tripped_breaker_blocks_submission(db):
    lease = make_lease(db)
    preview = service.preview_trip_production_circuit_breaker(
        db, wallet_address=WALLET, reason_codes=["MANUAL_STOP"], source_type="MANUAL", source_id=None,
        idempotency_token="m46-trip-submit", evaluated_at=NOW,
    )
    service.trip_production_circuit_breaker(
        db, wallet_address=WALLET, reason_codes=["MANUAL_STOP"], source_type="MANUAL", source_id=None,
        idempotency_token="m46-trip-submit", confirmation=preview["confirmation"], settings_object=settings_for_m46(), tripped_at=NOW,
    )
    result = service.validate_progressive_automation_lease_for_submission(
        db, lease_id=lease["lease_id"], side="BUY", token_mint=TOKEN, requested_budget_sol="0.003",
        wallet_address=WALLET, assisted_micro_live_pilot_id="pilot-present", settings_object=settings_for_m46(), evaluated_at=NOW,
    )
    assert result["ready"] is False
    assert any("TRIPPED" in code for code in result["reason_codes"])


def test_reset_breaker_requires_healthy_state(db):
    # create a breaker directly without a health snapshot
    row = CanonicalParserProductionCircuitBreaker(
        breaker_id="breaker-reset-test".ljust(36, "0")[:36], breaker_key="a" * 64,
        scope="M46_PRODUCTION_CIRCUIT_BREAKER", wallet_address=WALLET, network="mainnet-beta",
        status="TRIPPED", reason_codes=["TEST"], source_type="MANUAL", source_id=None,
        trip_count=1, reset_count=0, breaker_snapshot={}, evidence_hash="b" * 64,
        actor_label="TEST", note=None, tripped_at=NOW, reset_at=None,
        latest_event_sequence=1, latest_event_hash="c" * 64,
    )
    db.add(row); db.commit()
    preview = service.preview_reset_production_circuit_breaker(db, breaker_id=row.breaker_id, resolution_evidence="resolved evidence", evaluated_at=NOW)
    assert preview["status"] == "BLOCKED"
    assert "M46_RESET_HEALTH_NOT_READY" in preview["reason_codes"]


def test_reset_breaker_requires_new_lease_after_trip(db):
    lease = make_lease(db)
    trip_preview = service.preview_trip_production_circuit_breaker(
        db, wallet_address=WALLET, reason_codes=["TEST"], source_type="MANUAL", source_id=None,
        idempotency_token="m46-trip-reset", evaluated_at=NOW + timedelta(minutes=1),
    )
    breaker = service.trip_production_circuit_breaker(
        db, wallet_address=WALLET, reason_codes=["TEST"], source_type="MANUAL", source_id=None,
        idempotency_token="m46-trip-reset", confirmation=trip_preview["confirmation"], settings_object=settings_for_m46(), tripped_at=NOW + timedelta(minutes=1),
    )
    reset_preview = service.preview_reset_production_circuit_breaker(
        db, breaker_id=breaker["breaker_id"], resolution_evidence="all checks resolved", evaluated_at=NOW + timedelta(minutes=2),
    )
    assert reset_preview["status"] == "READY"
    result = service.reset_production_circuit_breaker(
        db, breaker_id=breaker["breaker_id"], resolution_evidence="all checks resolved",
        confirmation=reset_preview["confirmation"], settings_object=settings_for_m46(), reset_at=NOW + timedelta(minutes=2),
    )
    assert result["status"] == "CLEAR"
    old_lease = service.get_progressive_automation_lease(db, lease["lease_id"], evaluated_at=NOW + timedelta(minutes=2))
    assert old_lease["status"] == "TRIPPED"


def test_active_incident_blocks_assessment(db):
    add_healthy_snapshot(db)
    add_completed_pilot(db, 1)
    incident = CanonicalParserLiveIncident(
        incident_id="m46-incident".ljust(36, "0")[:36], incident_key="d" * 64,
        scope="M41_LIVE_INCIDENT_RESPONSE", source_type="MANUAL", source_id="manual",
        category="TEST", severity="HIGH", status="OPEN", freeze_new_submissions=True,
        reason_codes=["TEST"], incident_snapshot={}, evidence_hash="e" * 64,
        actor_label="TEST", note=None, detected_at=NOW, acknowledged_at=None,
        resolved_at=None, latest_event_sequence=1, latest_event_hash="f" * 64,
    )
    db.add(incident); db.commit()
    preview = service.preview_production_hardening_assessment(
        db, wallet_address=WALLET, token_mint=TOKEN, requested_stage="ASSISTED",
        requested_max_budget_sol="0.003", requested_max_submissions=2,
        idempotency_token="m46-incident-block", settings_object=settings_for_m46(), evaluated_at=NOW,
    )
    assert preview["status"] == "BLOCKED"
    assert "M46_ACTIVE_INCIDENTS_PRESENT" in preview["reason_codes"]



def test_observe_only_assessment_cannot_issue_operational_lease(db):
    add_healthy_snapshot(db)
    args = dict(
        wallet_address=WALLET,
        token_mint=TOKEN,
        requested_stage="OBSERVE_ONLY",
        requested_max_budget_sol="0",
        requested_max_submissions=0,
        idempotency_token="m46-observe-assessment",
    )
    preview = service.preview_production_hardening_assessment(
        db, **args, settings_object=settings_for_m46(), evaluated_at=NOW
    )
    assessment = service.assess_production_hardening(
        db, **args, confirmation=preview["confirmation"],
        settings_object=settings_for_m46(), assessed_at=NOW,
    )
    lease_preview = service.preview_progressive_automation_lease(
        db, assessment_id=assessment["assessment_id"], validity_minutes=10,
        idempotency_token="m46-observe-lease", settings_object=settings_for_m46(), evaluated_at=NOW,
    )
    assert lease_preview["status"] == "BLOCKED"
    assert "M46_OBSERVE_ONLY_LEASE_NOT_REQUIRED" in lease_preview["reason_codes"]


def test_lease_consumption_is_idempotent_by_submission_id(db):
    lease = make_lease(db)
    kwargs = dict(
        lease_id=lease["lease_id"], submission_id="same-submission", side="BUY",
        token_mint=TOKEN, requested_budget_sol="0.003", wallet_address=WALLET,
        assisted_micro_live_pilot_id="pilot-present", settings_object=settings_for_m46(),
        consumed_at=NOW + timedelta(seconds=1),
    )
    first = service.consume_progressive_automation_lease_submission_slot(db, **kwargs)
    second = service.consume_progressive_automation_lease_submission_slot(db, **kwargs)
    assert first["used_submission_count"] == 1
    assert second["used_submission_count"] == 1
    assert db.query(CanonicalParserProgressiveAutomationLeaseEvent).count() == 2


def test_circuit_breaker_trip_is_idempotent(db):
    add_healthy_snapshot(db)
    preview = service.preview_trip_production_circuit_breaker(
        db, wallet_address=WALLET, reason_codes=["MANUAL_STOP"], source_type="MANUAL",
        source_id=None, idempotency_token="m46-idempotent-trip", evaluated_at=NOW,
    )
    kwargs = dict(
        wallet_address=WALLET, reason_codes=["MANUAL_STOP"], source_type="MANUAL",
        source_id=None, idempotency_token="m46-idempotent-trip", confirmation=preview["confirmation"],
        settings_object=settings_for_m46(), tripped_at=NOW,
    )
    first = service.trip_production_circuit_breaker(db, **kwargs)
    second = service.trip_production_circuit_breaker(db, **kwargs)
    assert first["breaker_id"] == second["breaker_id"]
    assert second["trip_count"] == 1
    assert db.query(CanonicalParserProductionCircuitBreakerEvent).count() == 1

def test_m46_openapi_and_static_safety_hooks():
    paths = app.openapi()["paths"]
    required = {
        "/integrity/parser-progressive-automation/status",
        "/integrity/parser-progressive-automation/assessment-preview",
        "/integrity/parser-progressive-automation/assess",
        "/integrity/parser-progressive-automation/lease-preview",
        "/integrity/parser-progressive-automation/lease/issue",
        "/integrity/parser-progressive-automation/lease/revoke",
        "/integrity/parser-progressive-automation/circuit-breaker-preview",
        "/integrity/parser-progressive-automation/circuit-breaker/trip",
        "/integrity/parser-progressive-automation/circuit-breaker-reset-preview",
        "/integrity/parser-progressive-automation/circuit-breaker/reset",
        "/integrity/parser-progressive-automation/assessments/{assessment_id}",
        "/integrity/parser-progressive-automation/leases/{lease_id}",
        "/integrity/parser-progressive-automation/circuit-breakers/{wallet_address}",
        "/integrity/parser-progressive-automation/resolve",
    }
    assert required.issubset(paths)
    m38 = Path("backend/app/services/blockchain_parser_controlled_live_submission_service.py").read_text()
    for hook in (
        "validate_progressive_automation_lease_for_submission",
        "consume_progressive_automation_lease_submission_slot",
        "progressive_automation_lease_id",
        "M46_PROGRESSIVE_AUTOMATION_WALLET_MISMATCH",
    ):
        assert hook in m38 + Path(service.__file__).read_text()
    tree = ast.parse(Path(service.__file__).read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "backend.app.services.solana_transaction_signer" not in imports
    assert "backend.app.services.live_copy_trading_engine" not in imports
    source = Path(service.__file__).read_text()
    assert "send_signed_transaction_base64" not in source
    assert "LIVE_TRADING_PRIVATE_KEY" not in source
    assert '"automatic_dispatch": False' in source
