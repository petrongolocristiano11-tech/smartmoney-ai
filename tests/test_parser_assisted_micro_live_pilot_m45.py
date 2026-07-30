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
    CanonicalParserAssistedMicroLivePilotChecklist,
    CanonicalParserAssistedMicroLivePilotCheckpoint,
    CanonicalParserAssistedMicroLivePilotEvent,
    CanonicalParserControlledLiveSubmission,
    CanonicalParserGovernedLiveExitIntent,
    CanonicalParserGovernedLivePosition,
    CanonicalParserLiveObservabilitySnapshot,
    CanonicalParserLiveOnchainSettlement,
    CanonicalParserPreproductionCertification,
)
import backend.app.services.blockchain_parser_assisted_micro_live_pilot_service as service

NOW = datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc)
WALLET = "1" * 32
TOKEN = "2" * 32
CERT_ID = "certification-000000000000000000001"[:36]


def settings_for_m45(**overrides):
    values = {
        "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_PILOT_ENABLED": True,
        "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_PILOT_GUARD_ENABLED": True,
        "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_VALIDITY_MINUTES": 60,
        "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_ENTRY_BUDGET_SOL": 0.005,
        "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_TOTAL_FEE_SOL": 0.001,
        "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_POSITION_DURATION_MINUTES": 30,
        "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_REQUIRE_HEALTHY_OBSERVABILITY": True,
        "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_REQUIRE_ACTIVE_CERTIFICATION": True,
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


def add_snapshot(db: Session, *, observed_at=NOW, expires_at=None, suffix="a"):
    row = CanonicalParserLiveObservabilitySnapshot(
        snapshot_id=f"snapshot-{suffix}".ljust(36, "0")[:36],
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
        observed_at=observed_at,
        expires_at=expires_at or observed_at + timedelta(hours=2),
    )
    db.add(row)
    db.commit()
    return row


def add_certification(db: Session):
    snapshot = add_snapshot(db)
    row = CanonicalParserPreproductionCertification(
        certification_id=CERT_ID,
        certification_key="c" * 64,
        scope="M44_PREPRODUCTION_CERTIFICATION",
        environment="PREPRODUCTION",
        status="ACTIVE",
        observability_snapshot_db_id=snapshot.id,
        observability_snapshot_id=snapshot.snapshot_id,
        git_commit_sha="d" * 40,
        alembic_head="b0e2f5a8c964",
        fastapi_version="0.138.2",
        clean_worktree_attested=True,
        full_test_count=1160,
        full_test_failures=0,
        test_evidence_hash="e" * 64,
        check_summary={"pass_count": 12, "fail_count": 0},
        evidence_snapshot={},
        evidence_hash="f" * 64,
        actor_label="TEST",
        note=None,
        certified_at=NOW,
        expires_at=NOW + timedelta(hours=2),
        revoked_at=None,
        latest_event_sequence=1,
        latest_event_hash="1" * 64,
    )
    db.add(row)
    db.commit()
    return row


def issue_pilot(db: Session, *, token="m45-pilot-001"):
    cert = db.scalar(select(CanonicalParserPreproductionCertification)) or add_certification(db)
    args = {
        "certification_id": cert.certification_id,
        "wallet_address": WALLET,
        "token_mint": TOKEN,
        "max_entry_budget_sol": "0.003",
        "max_total_fee_sol": "0.0005",
        "max_position_duration_minutes": 20,
        "validity_minutes": 45,
        "idempotency_token": token,
        "settings_object": settings_for_m45(),
    }
    preview = service.preview_assisted_micro_live_pilot(db, **args, evaluated_at=NOW)
    result = service.issue_assisted_micro_live_pilot(
        db, **args, confirmation=preview["confirmation"], issued_at=NOW
    )
    return result


def attest_all(db: Session, pilot_id: str):
    for code in service.REQUIRED_CHECKLIST_ITEMS:
        preview = service.preview_assisted_micro_live_checklist_attestation(
            db,
            pilot_id=pilot_id,
            item_code=code,
            status="PASS",
            evidence=f"verified {code}",
            evaluated_at=NOW + timedelta(seconds=1),
        )
        service.attest_assisted_micro_live_checklist(
            db,
            pilot_id=pilot_id,
            item_code=code,
            status="PASS",
            evidence=f"verified {code}",
            confirmation=preview["confirmation"],
            settings_object=settings_for_m45(),
            attested_at=NOW + timedelta(seconds=1),
        )


def arm_pilot(db: Session):
    pilot = issue_pilot(db)
    attest_all(db, pilot["pilot_id"])
    preview = service.preview_arm_assisted_micro_live_pilot(
        db, pilot_id=pilot["pilot_id"], settings_object=settings_for_m45(), evaluated_at=NOW + timedelta(minutes=1)
    )
    result = service.arm_assisted_micro_live_pilot(
        db,
        pilot_id=pilot["pilot_id"],
        confirmation=preview["confirmation"],
        settings_object=settings_for_m45(),
        armed_at=NOW + timedelta(minutes=1),
    )
    return result


def add_submission(db: Session, *, submission_id: str, side: str, status="FINALIZED", keychar="3"):
    row = CanonicalParserControlledLiveSubmission(
        submission_id=submission_id,
        submission_key=keychar * 64,
        scope="M38_MANUAL_CONTROLLED_LIVE_SUBMISSION",
        approval_db_id=100 if side == "BUY" else 101,
        approval_id=("approval-" + side).ljust(36, "0")[:36],
        dry_run_id=("dry-run-" + side).ljust(36, "0")[:36],
        micro_live_permit_id=("permit-" + side).ljust(36, "0")[:36],
        status=status,
        side=side,
        token_mint=TOKEN,
        reserved_budget_sol=Decimal("0.003") if side == "BUY" else Decimal("0"),
        signed_transaction_hash=keychar * 64,
        expected_signature=("sig-" + side).ljust(44, "0"),
        rpc_signature=("rpc-" + side).ljust(44, "0"),
        send_attempted=True,
        confirmation_status="finalized" if status == "FINALIZED" else None,
        confirmation_slot=123,
        chain_error=None,
        reason_codes=[],
        reservation_snapshot={},
        submission_snapshot={},
        evidence_hash=(str((int(keychar) + 1) % 10)) * 64,
        actor_label="TEST",
        note=None,
        reserved_at=NOW,
        submitted_at=NOW,
        reconciled_at=NOW,
        confirmed_at=NOW,
        finalized_at=NOW,
    )
    db.add(row)
    db.commit()
    return row


def add_settlement(db: Session, *, settlement_id: str, submission_id: str, side: str, position_id: str, fee=5000, minute=2, keychar="5"):
    row = CanonicalParserLiveOnchainSettlement(
        settlement_id=settlement_id,
        settlement_key=keychar * 64,
        scope="M39_AUTHORITATIVE_ONCHAIN_SETTLEMENT",
        submission_db_id=200 if side == "BUY" else 201,
        submission_id=submission_id,
        dry_run_id=("dry-" + side).ljust(36, "0")[:36],
        micro_live_permit_id=("permit-" + side).ljust(36, "0")[:36],
        decision_result_id=("decision-" + side).ljust(36, "0")[:36],
        position_id=position_id,
        status="SETTLED",
        side=side,
        token_mint=TOKEN,
        wallet_address=WALLET,
        rpc_signature=("rpc-settle-" + side).ljust(44, "0"),
        confirmation_status="finalized",
        slot=123,
        block_time=NOW + timedelta(minutes=minute),
        fee_lamports=Decimal(fee),
        wallet_sol_delta_lamports=Decimal(-3000000 if side == "BUY" else 3500000),
        token_delta_raw=Decimal(100 if side == "BUY" else -100),
        actual_input_amount_raw=Decimal(3000000 if side == "BUY" else 100),
        actual_output_amount_raw=Decimal(100 if side == "BUY" else 3500000),
        actual_input_sol=Decimal("0.003") if side == "BUY" else Decimal("0"),
        actual_output_sol=Decimal("0") if side == "BUY" else Decimal("0.0035"),
        reason_codes=[],
        transaction_snapshot={},
        attribution_snapshot={},
        evidence_hash=(str((int(keychar) + 1) % 10)) * 64,
        actor_label="TEST",
        note=None,
        settled_at=NOW + timedelta(minutes=minute),
    )
    db.add(row)
    db.commit()
    return row


def add_position(db: Session, *, position_id: str, entry_settlement_id: str, status="OPEN", quantity=100):
    row = CanonicalParserGovernedLivePosition(
        position_id=position_id,
        position_key="7" * 64,
        scope="M39_GOVERNED_LIVE_POSITION_LEDGER",
        entry_settlement_db_id=300,
        entry_settlement_id=entry_settlement_id,
        last_settlement_id=entry_settlement_id,
        micro_live_permit_id="permit-position".ljust(36, "0")[:36],
        decision_result_id="decision-position".ljust(36, "0")[:36],
        wallet_address=WALLET,
        token_mint=TOKEN,
        status=status,
        quantity_raw=Decimal(quantity),
        cost_basis_sol=Decimal("0.003"),
        realized_proceeds_sol=Decimal("0.0035") if status == "CLOSED" else Decimal("0"),
        realized_pnl_sol=Decimal("0.0005") if status == "CLOSED" else Decimal("0"),
        high_watermark_value_sol=Decimal("0.0035"),
        high_watermark_roi_percent=Decimal("16.6"),
        exit_plan={},
        position_snapshot={},
        evidence_hash="8" * 64,
        position_version=1,
        opened_at=NOW + timedelta(minutes=2),
        last_assessed_at=NOW + timedelta(minutes=3),
        closed_at=NOW + timedelta(minutes=10) if status == "CLOSED" else None,
    )
    db.add(row)
    db.commit()
    return row


def add_exit_intent(db: Session, *, intent_id: str, position_id: str):
    row = CanonicalParserGovernedLiveExitIntent(
        intent_id=intent_id,
        intent_key="9" * 64,
        scope="M40_MANUAL_GOVERNED_LIVE_EXIT_INTENT",
        position_db_id=400,
        position_id=position_id,
        assessment_db_id=401,
        assessment_id="assessment-exit".ljust(36, "0")[:36],
        micro_live_permit_id="permit-exit".ljust(36, "0")[:36],
        decision_result_id="decision-exit".ljust(36, "0")[:36],
        status="ACTIVE",
        reason_code="MANUAL_PILOT_EXIT",
        quantity_raw=Decimal(100),
        percentage=Decimal("100"),
        expected_output_sol=Decimal("0.0035"),
        minimum_output_sol=Decimal("0.0034"),
        intent_snapshot={},
        evidence_hash="a" * 64,
        actor_label="TEST",
        note=None,
        issued_at=NOW + timedelta(minutes=4),
        expires_at=NOW + timedelta(minutes=20),
        revoked_at=None,
        consumed_at=None,
        latest_event_sequence=1,
        latest_event_hash="b" * 64,
    )
    db.add(row)
    db.commit()
    return row


def test_m45_flags_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_ASSISTED_MICRO_LIVE_PILOT_ENABLED is False
    assert configured.CANONICAL_PARSER_ASSISTED_MICRO_LIVE_PILOT_GUARD_ENABLED is False


def test_m45_models_and_migration_registered():
    for table in (
        "canonical_parser_assisted_micro_live_pilots",
        "canonical_parser_assisted_micro_live_pilot_checklist",
        "canonical_parser_assisted_micro_live_pilot_checkpoints",
        "canonical_parser_assisted_micro_live_pilot_events",
    ):
        assert table in Base.metadata.tables
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("b0e2f5a8c964").down_revision == "a9d1e4f7b853"
    assert scripts.get_heads() == ["c1f3a6b9d075"]


def test_preview_ready_and_bounded(db):
    cert = add_certification(db)
    preview = service.preview_assisted_micro_live_pilot(
        db,
        certification_id=cert.certification_id,
        wallet_address=WALLET,
        token_mint=TOKEN,
        max_entry_budget_sol="0.003",
        max_total_fee_sol="0.0005",
        max_position_duration_minutes=20,
        validity_minutes=45,
        idempotency_token="m45-preview-ready",
        settings_object=settings_for_m45(),
        evaluated_at=NOW,
    )
    assert preview["status"] == "READY"
    assert preview["safety"]["automatic_submission"] is False


def test_preview_blocks_budget_and_validity(db):
    cert = add_certification(db)
    preview = service.preview_assisted_micro_live_pilot(
        db,
        certification_id=cert.certification_id,
        wallet_address=WALLET,
        token_mint=TOKEN,
        max_entry_budget_sol="0.006",
        max_total_fee_sol="0.002",
        max_position_duration_minutes=40,
        validity_minutes=90,
        idempotency_token="m45-preview-blocked",
        settings_object=settings_for_m45(),
        evaluated_at=NOW,
    )
    assert preview["status"] == "BLOCKED"
    assert "M45_ENTRY_BUDGET_EXCEEDED" in preview["reason_codes"]
    assert "M45_VALIDITY_EXCEEDED" in preview["reason_codes"]


def test_issue_requires_enabled_flag(db):
    cert = add_certification(db)
    args = dict(
        certification_id=cert.certification_id,
        wallet_address=WALLET,
        token_mint=TOKEN,
        max_entry_budget_sol="0.003",
        max_total_fee_sol="0.0005",
        max_position_duration_minutes=20,
        validity_minutes=45,
        idempotency_token="m45-disabled",
    )
    preview = service.preview_assisted_micro_live_pilot(db, **args, settings_object=settings_for_m45(), evaluated_at=NOW)
    with pytest.raises(service.CanonicalParserAssistedMicroLivePilotError) as exc:
        service.issue_assisted_micro_live_pilot(
            db,
            **args,
            confirmation=preview["confirmation"],
            settings_object=settings_for_m45(CANONICAL_PARSER_ASSISTED_MICRO_LIVE_PILOT_ENABLED=False),
            issued_at=NOW,
        )
    assert exc.value.code == "M45_DISABLED"


def test_issue_persists_pilot_and_initial_event(db):
    result = issue_pilot(db)
    assert result["status"] == "PLANNED"
    assert db.query(CanonicalParserAssistedMicroLivePilot).count() == 1
    assert db.query(CanonicalParserAssistedMicroLivePilotEvent).count() == 1


def test_checklist_unknown_item_blocked(db):
    pilot = issue_pilot(db)
    preview = service.preview_assisted_micro_live_checklist_attestation(
        db, pilot_id=pilot["pilot_id"], item_code="UNKNOWN", status="PASS", evidence="not valid", evaluated_at=NOW
    )
    assert preview["status"] == "BLOCKED"
    assert "M45_UNKNOWN_CHECKLIST_ITEM" in preview["reason_codes"]



def test_checklist_confirmation_remains_valid_across_request_delay(db):
    pilot = issue_pilot(db)
    code = service.REQUIRED_CHECKLIST_ITEMS[0]
    evidence = "operator presence verified"

    preview = service.preview_assisted_micro_live_checklist_attestation(
        db,
        pilot_id=pilot["pilot_id"],
        item_code=code,
        status="PASS",
        evidence=evidence,
        evaluated_at=NOW + timedelta(seconds=1),
    )
    delayed_preview = service.preview_assisted_micro_live_checklist_attestation(
        db,
        pilot_id=pilot["pilot_id"],
        item_code=code,
        status="PASS",
        evidence=evidence,
        evaluated_at=NOW + timedelta(seconds=2),
    )

    assert preview["confirmation"] == delayed_preview["confirmation"]
    assert preview["evidence_hash"] == delayed_preview["evidence_hash"]
    assert (
        preview["evidence"]["evaluated_at"]
        != delayed_preview["evidence"]["evaluated_at"]
    )

    result = service.attest_assisted_micro_live_checklist(
        db,
        pilot_id=pilot["pilot_id"],
        item_code=code,
        status="PASS",
        evidence=evidence,
        confirmation=preview["confirmation"],
        settings_object=settings_for_m45(),
        attested_at=NOW + timedelta(seconds=2),
    )

    assert result["status"] == "PLANNED"
    assert result["passed_checklist_count"] == 1
    assert result["checklist"][0]["item_code"] == code
    assert result["checklist"][0]["status"] == "PASS"


def test_checklist_is_immutable(db):
    pilot = issue_pilot(db)
    code = service.REQUIRED_CHECKLIST_ITEMS[0]
    preview = service.preview_assisted_micro_live_checklist_attestation(
        db, pilot_id=pilot["pilot_id"], item_code=code, status="PASS", evidence="verified", evaluated_at=NOW
    )
    service.attest_assisted_micro_live_checklist(
        db, pilot_id=pilot["pilot_id"], item_code=code, status="PASS", evidence="verified", confirmation=preview["confirmation"], settings_object=settings_for_m45(), attested_at=NOW
    )
    second = service.preview_assisted_micro_live_checklist_attestation(
        db, pilot_id=pilot["pilot_id"], item_code=code, status="FAIL", evidence="changed", evaluated_at=NOW
    )
    assert "M45_CHECKLIST_ITEM_ALREADY_ATTESTED" in second["reason_codes"]
    assert db.query(CanonicalParserAssistedMicroLivePilotChecklist).count() == 1


def test_arm_blocks_incomplete_checklist(db):
    pilot = issue_pilot(db)
    preview = service.preview_arm_assisted_micro_live_pilot(db, pilot_id=pilot["pilot_id"], settings_object=settings_for_m45(), evaluated_at=NOW)
    assert preview["status"] == "BLOCKED"
    assert "M45_CHECKLIST_INCOMPLETE" in preview["reason_codes"]


def test_complete_checklist_arms_pilot(db):
    result = arm_pilot(db)
    assert result["status"] == "ARMED"
    assert result["passed_checklist_count"] == len(service.REQUIRED_CHECKLIST_ITEMS)


def test_pilot_guard_disabled_is_non_intrusive(db):
    result = service.validate_assisted_micro_live_pilot_for_submission(
        db,
        pilot_id=None,
        wallet_address=WALLET,
        side="BUY",
        token_mint=TOKEN,
        requested_budget_sol="0.003",
        settings_object=settings_for_m45(CANONICAL_PARSER_ASSISTED_MICRO_LIVE_PILOT_GUARD_ENABLED=False),
        evaluated_at=NOW,
    )
    assert result["required"] is False
    assert result["ready"] is True


def test_buy_validation_binds_wallet_token_and_budget(db):
    pilot = arm_pilot(db)
    ready = service.validate_assisted_micro_live_pilot_for_submission(
        db, pilot_id=pilot["pilot_id"], wallet_address=WALLET, side="BUY", token_mint=TOKEN, requested_budget_sol="0.003", settings_object=settings_for_m45(), evaluated_at=NOW + timedelta(minutes=1)
    )
    blocked = service.validate_assisted_micro_live_pilot_for_submission(
        db, pilot_id=pilot["pilot_id"], wallet_address="3" * 32, side="BUY", token_mint=TOKEN, requested_budget_sol="0.004", settings_object=settings_for_m45(), evaluated_at=NOW + timedelta(minutes=1)
    )
    assert ready["ready"] is True
    assert "M45_ASSISTED_PILOT_WALLET_MISMATCH" in blocked["reason_codes"]
    assert "M45_ASSISTED_PILOT_ENTRY_BUDGET_EXCEEDED" in blocked["reason_codes"]


def test_entry_slot_is_single_use(db):
    pilot = arm_pilot(db)
    consumed = service.consume_assisted_micro_live_pilot_submission_slot(
        db, pilot_id=pilot["pilot_id"], submission_id="entry-submission".ljust(36, "0")[:36], wallet_address=WALLET, side="BUY", token_mint=TOKEN, requested_budget_sol="0.003", settings_object=settings_for_m45(), consumed_at=NOW + timedelta(minutes=1)
    )
    db.commit()
    assert consumed["consumed"] is True
    second = service.validate_assisted_micro_live_pilot_for_submission(
        db, pilot_id=pilot["pilot_id"], wallet_address=WALLET, side="BUY", token_mint=TOKEN, requested_budget_sol="0.003", settings_object=settings_for_m45(), evaluated_at=NOW + timedelta(minutes=1)
    )
    assert second["ready"] is False


def test_entry_reconcile_requires_finalized_submission(db):
    pilot = issue_pilot(db)
    row = db.scalar(select(CanonicalParserAssistedMicroLivePilot))
    row.status = "ENTRY_SUBMITTED"
    row.entry_submission_id = "entry-submission".ljust(36, "0")[:36]
    db.commit()
    add_submission(db, submission_id=row.entry_submission_id, side="BUY", status="SUBMITTED")
    preview = service.preview_assisted_micro_live_pilot_checkpoint(
        db, pilot_id=pilot["pilot_id"], checkpoint_type="ENTRY_RECONCILED", source_id=row.entry_submission_id, idempotency_token="m45-entry-not-final", evaluated_at=NOW
    )
    assert preview["status"] == "BLOCKED"
    assert "M45_ENTRY_SUBMISSION_NOT_FINALIZED" in preview["reason_codes"]


def test_entry_reconcile_checkpoint_advances_stage(db):
    pilot = issue_pilot(db)
    row = db.scalar(select(CanonicalParserAssistedMicroLivePilot))
    row.status = "ENTRY_SUBMITTED"
    row.entry_submission_id = "entry-submission".ljust(36, "0")[:36]
    db.commit()
    add_submission(db, submission_id=row.entry_submission_id, side="BUY", status="FINALIZED")
    preview = service.preview_assisted_micro_live_pilot_checkpoint(
        db, pilot_id=pilot["pilot_id"], checkpoint_type="ENTRY_RECONCILED", source_id=row.entry_submission_id, idempotency_token="m45-entry-final", evaluated_at=NOW
    )
    result = service.record_assisted_micro_live_pilot_checkpoint(
        db, pilot_id=pilot["pilot_id"], checkpoint_type="ENTRY_RECONCILED", source_id=row.entry_submission_id, idempotency_token="m45-entry-final", confirmation=preview["confirmation"], settings_object=settings_for_m45(), checked_at=NOW
    )
    assert result["status"] == "ENTRY_RECONCILED"
    assert db.query(CanonicalParserAssistedMicroLivePilotCheckpoint).count() == 1


def test_entry_settlement_links_position(db):
    pilot = issue_pilot(db)
    row = db.scalar(select(CanonicalParserAssistedMicroLivePilot))
    row.status = "ENTRY_RECONCILED"
    row.entry_submission_id = "entry-submission".ljust(36, "0")[:36]
    db.commit()
    position_id = "position-entry".ljust(36, "0")[:36]
    settlement_id = "settlement-entry".ljust(36, "0")[:36]
    add_settlement(db, settlement_id=settlement_id, submission_id=row.entry_submission_id, side="BUY", position_id=position_id)
    add_position(db, position_id=position_id, entry_settlement_id=settlement_id)
    preview = service.preview_assisted_micro_live_pilot_checkpoint(
        db, pilot_id=pilot["pilot_id"], checkpoint_type="ENTRY_SETTLED", source_id=settlement_id, idempotency_token="m45-entry-settled", evaluated_at=NOW + timedelta(minutes=3)
    )
    result = service.record_assisted_micro_live_pilot_checkpoint(
        db, pilot_id=pilot["pilot_id"], checkpoint_type="ENTRY_SETTLED", source_id=settlement_id, idempotency_token="m45-entry-settled", confirmation=preview["confirmation"], settings_object=settings_for_m45(), checked_at=NOW + timedelta(minutes=3)
    )
    assert result["status"] == "ENTRY_SETTLED"
    assert result["position_id"] == position_id


def test_exit_intent_enables_sell_and_exit_slot_single_use(db):
    pilot = issue_pilot(db)
    row = db.scalar(select(CanonicalParserAssistedMicroLivePilot))
    row.status = "ENTRY_SETTLED"
    row.position_id = "position-exit".ljust(36, "0")[:36]
    db.commit()
    intent_id = "intent-exit".ljust(36, "0")[:36]
    add_exit_intent(db, intent_id=intent_id, position_id=row.position_id)
    preview = service.preview_assisted_micro_live_pilot_checkpoint(
        db, pilot_id=pilot["pilot_id"], checkpoint_type="EXIT_INTENT_VERIFIED", source_id=intent_id, idempotency_token="m45-exit-intent", evaluated_at=NOW + timedelta(minutes=5)
    )
    result = service.record_assisted_micro_live_pilot_checkpoint(
        db, pilot_id=pilot["pilot_id"], checkpoint_type="EXIT_INTENT_VERIFIED", source_id=intent_id, idempotency_token="m45-exit-intent", confirmation=preview["confirmation"], settings_object=settings_for_m45(), checked_at=NOW + timedelta(minutes=5)
    )
    assert result["status"] == "EXIT_READY"
    validation = service.validate_assisted_micro_live_pilot_for_submission(
        db, pilot_id=pilot["pilot_id"], wallet_address=WALLET, side="SELL", token_mint=TOKEN, requested_budget_sol="0", settings_object=settings_for_m45(), evaluated_at=NOW + timedelta(minutes=5)
    )
    assert validation["ready"] is True
    service.consume_assisted_micro_live_pilot_submission_slot(
        db, pilot_id=pilot["pilot_id"], submission_id="exit-submission".ljust(36, "0")[:36], wallet_address=WALLET, side="SELL", token_mint=TOKEN, requested_budget_sol="0", settings_object=settings_for_m45(), consumed_at=NOW + timedelta(minutes=5)
    )
    db.commit()
    second = service.validate_assisted_micro_live_pilot_for_submission(
        db, pilot_id=pilot["pilot_id"], wallet_address=WALLET, side="SELL", token_mint=TOKEN, requested_budget_sol="0", settings_object=settings_for_m45(), evaluated_at=NOW + timedelta(minutes=5)
    )
    assert second["ready"] is False


def test_completion_requires_closed_position_and_healthy_post_snapshot(db):
    pilot = issue_pilot(db)
    row = db.scalar(select(CanonicalParserAssistedMicroLivePilot))
    entry_submission = "entry-complete".ljust(36, "0")[:36]
    exit_submission = "exit-complete".ljust(36, "0")[:36]
    entry_settlement = "entry-settlement".ljust(36, "0")[:36]
    exit_settlement = "exit-settlement".ljust(36, "0")[:36]
    position_id = "position-complete".ljust(36, "0")[:36]
    add_settlement(db, settlement_id=entry_settlement, submission_id=entry_submission, side="BUY", position_id=position_id, fee=5000, minute=2, keychar="5")
    add_settlement(db, settlement_id=exit_settlement, submission_id=exit_submission, side="SELL", position_id=position_id, fee=5000, minute=10, keychar="6")
    add_position(db, position_id=position_id, entry_settlement_id=entry_settlement, status="CLOSED", quantity=0)
    post = add_snapshot(db, observed_at=NOW + timedelta(minutes=11), expires_at=NOW + timedelta(hours=1), suffix="z")
    row = db.scalar(select(CanonicalParserAssistedMicroLivePilot))
    row.status = "EXIT_SETTLED"
    row.entry_submission_id = entry_submission
    row.entry_settlement_id = entry_settlement
    row.position_id = position_id
    row.exit_intent_id = "intent-complete".ljust(36, "0")[:36]
    row.exit_submission_id = exit_submission
    row.exit_settlement_id = exit_settlement
    row.post_observability_snapshot_id = post.snapshot_id
    db.commit()
    preview = service.preview_complete_assisted_micro_live_pilot(db, pilot_id=pilot["pilot_id"], evaluated_at=NOW + timedelta(minutes=12))
    assert preview["status"] == "READY"
    result = service.complete_assisted_micro_live_pilot(
        db, pilot_id=pilot["pilot_id"], confirmation=preview["confirmation"], settings_object=settings_for_m45(), completed_at=NOW + timedelta(minutes=12)
    )
    assert result["status"] == "COMPLETED"
    assert result["completion_snapshot"]["position_status"] == "CLOSED"


def test_abort_is_fail_closed_and_marks_manual_recovery(db):
    pilot = issue_pilot(db)
    row = db.scalar(select(CanonicalParserAssistedMicroLivePilot))
    row.status = "ENTRY_SETTLED"
    row.position_id = "position-open".ljust(36, "0")[:36]
    db.commit()
    result = service.abort_assisted_micro_live_pilot(
        db,
        pilot_id=pilot["pilot_id"],
        reason="operator stopped pilot",
        confirmation=f"{service.ABORT_PREFIX}:{pilot['pilot_id']}:{pilot['evidence_hash']}",
        settings_object=settings_for_m45(),
        aborted_at=NOW + timedelta(minutes=3),
    )
    assert result["status"] == "ABORTED"
    assert result["completion_snapshot"]["manual_position_recovery_required"] is True



def test_preview_rejects_non_positive_limits(db):
    cert = add_certification(db)
    preview = service.preview_assisted_micro_live_pilot(
        db,
        certification_id=cert.certification_id,
        wallet_address=WALLET,
        token_mint=TOKEN,
        max_entry_budget_sol="0",
        max_total_fee_sol="-0.0001",
        max_position_duration_minutes=0,
        validity_minutes=4,
        idempotency_token="m45-invalid-limits",
        settings_object=settings_for_m45(),
        evaluated_at=NOW,
    )
    assert preview["status"] == "BLOCKED"
    assert {
        "M45_ENTRY_BUDGET_NOT_POSITIVE",
        "M45_TOTAL_FEE_LIMIT_NEGATIVE",
        "M45_POSITION_DURATION_TOO_SHORT",
        "M45_VALIDITY_TOO_SHORT",
    }.issubset(preview["reason_codes"])


def test_checklist_preview_rejects_unknown_status_and_short_evidence(db):
    pilot = issue_pilot(db)
    preview = service.preview_assisted_micro_live_checklist_attestation(
        db,
        pilot_id=pilot["pilot_id"],
        item_code="OPERATOR_PRESENT",
        status="UNKNOWN",
        evidence="short",
        evaluated_at=NOW,
    )
    assert preview["status"] == "BLOCKED"
    assert "M45_INVALID_CHECKLIST_STATUS" in preview["reason_codes"]
    assert "M45_CHECKLIST_EVIDENCE_TOO_SHORT" in preview["reason_codes"]


def test_completion_blocks_expired_pilot(db):
    pilot = issue_pilot(db)
    row = db.scalar(select(CanonicalParserAssistedMicroLivePilot))
    row.status = "EXIT_SETTLED"
    row.expires_at = NOW + timedelta(minutes=1)
    db.commit()
    preview = service.preview_complete_assisted_micro_live_pilot(
        db,
        pilot_id=pilot["pilot_id"],
        evaluated_at=NOW + timedelta(minutes=2),
    )
    assert preview["status"] == "BLOCKED"
    assert "M45_PILOT_EXPIRED" in preview["reason_codes"]

def test_m45_openapi_and_static_safety_hooks():
    paths = app.openapi()["paths"]
    required = {
        "/integrity/parser-assisted-micro-live-pilot/status",
        "/integrity/parser-assisted-micro-live-pilot/pilot/issue",
        "/integrity/parser-assisted-micro-live-pilot/checklist/attest",
        "/integrity/parser-assisted-micro-live-pilot/arm",
        "/integrity/parser-assisted-micro-live-pilot/checkpoint",
        "/integrity/parser-assisted-micro-live-pilot/complete",
        "/integrity/parser-assisted-micro-live-pilot/abort",
        "/integrity/parser-assisted-micro-live-pilot/pilots/{pilot_id}",
    }
    assert required.issubset(paths)
    m38 = Path("backend/app/services/blockchain_parser_controlled_live_submission_service.py").read_text()
    assert "validate_assisted_micro_live_pilot_for_submission" in m38
    assert "consume_assisted_micro_live_pilot_submission_slot" in m38
    assert "assisted_micro_live_pilot_id" in m38
    tree = ast.parse(Path(service.__file__).read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "backend.app.services.solana_transaction_signer" not in imports
    assert "backend.app.services.live_copy_trading_engine" not in imports
    source = Path(service.__file__).read_text()
    assert "send_signed_transaction_base64" not in source
    assert "LIVE_TRADING_PRIVATE_KEY" not in source
