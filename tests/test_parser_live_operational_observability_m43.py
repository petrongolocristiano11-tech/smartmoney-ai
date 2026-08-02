from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401
from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserControlledLiveSubmission,
    CanonicalParserLiveObservabilitySnapshot,
    CanonicalParserLiveOperationalAlert,
    CanonicalParserLiveOperationalAlertEvent,
)
import backend.app.services.blockchain_parser_live_operational_observability_service as service

NOW = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)


def settings_for_m43(**overrides):
    values = {
        "CANONICAL_PARSER_LIVE_OBSERVABILITY_ENABLED": True,
        "CANONICAL_PARSER_LIVE_ALERT_LEDGER_ENABLED": True,
        "CANONICAL_PARSER_LIVE_OBSERVABILITY_SNAPSHOT_TTL_SECONDS": 60,
        "CANONICAL_PARSER_LIVE_OBSERVABILITY_STALE_SUBMISSION_SECONDS": 300,
        "CANONICAL_PARSER_LIVE_OBSERVABILITY_CRITICAL_OPEN_ALERT_THRESHOLD": 1,
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


def add_uncertain_submission(db: Session) -> CanonicalParserControlledLiveSubmission:
    row = CanonicalParserControlledLiveSubmission(
        submission_id="submission-0000000000000000000001"[:36],
        submission_key="a" * 64,
        scope="M38_MANUAL_CONTROLLED_LIVE_SUBMISSION",
        approval_db_id=1,
        approval_id="approval-00000000000000000000001"[:36],
        dry_run_id="dry-run-000000000000000000000001"[:36],
        micro_live_permit_id="permit-0000000000000000000000001"[:36],
        status="RECONCILIATION_REQUIRED",
        side="BUY",
        token_mint="2" * 32,
        reserved_budget_sol=Decimal("0.005"),
        signed_transaction_hash="b" * 64,
        expected_signature="sig-expected",
        rpc_signature="sig-expected",
        send_attempted=True,
        confirmation_status=None,
        confirmation_slot=None,
        chain_error={"message": "uncertain"},
        reason_codes=["RPC_SUBMISSION_OUTCOME_UNCERTAIN"],
        reservation_snapshot={},
        submission_snapshot={},
        evidence_hash="c" * 64,
        actor_label="TEST",
        note=None,
        reserved_at=NOW - timedelta(minutes=1),
        submitted_at=NOW - timedelta(minutes=1),
        reconciled_at=None,
        confirmed_at=None,
        finalized_at=None,
    )
    db.add(row)
    db.commit()
    return row


def observe(db: Session, *, token="m43-observation-001", settings_object=None):
    configured = settings_object or settings_for_m43()
    preview = service.preview_live_operational_observation(
        db,
        idempotency_token=token,
        settings_object=configured,
        observed_at=NOW,
    )
    result = service.observe_live_operations(
        db,
        idempotency_token=token,
        confirmation=preview["confirmation"],
        settings_object=configured,
        observed_at=NOW,
    )
    return preview, result


def test_m43_flags_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_LIVE_OBSERVABILITY_ENABLED is False
    assert configured.CANONICAL_PARSER_LIVE_ALERT_LEDGER_ENABLED is False


def test_m43_models_and_migration_are_registered():
    for table in (
        "canonical_parser_live_observability_snapshots",
        "canonical_parser_live_operational_alerts",
        "canonical_parser_live_operational_alert_events",
    ):
        assert table in Base.metadata.tables
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("f8c0d3e6a742").down_revision == "e7b9c2d5f631"
    assert len(scripts.get_heads()) == 1


def test_healthy_snapshot_is_persisted_and_idempotent(db):
    preview, first = observe(db)
    _, second = observe(db)
    assert preview["status"] == "HEALTHY"
    assert first["snapshot_id"] == second["snapshot_id"]
    assert db.query(CanonicalParserLiveObservabilitySnapshot).count() == 1


def test_uncertain_submission_makes_snapshot_critical(db):
    add_uncertain_submission(db)
    preview, result = observe(db)
    assert preview["status"] == "CRITICAL"
    assert result["uncertain_submission_count"] == 1
    assert "M38_RECONCILIATION_REQUIRED" in result["reason_codes"]


def test_alert_can_be_issued_from_snapshot_reason(db):
    add_uncertain_submission(db)
    _, snapshot = observe(db)
    preview = service.preview_live_operational_alert(
        db,
        snapshot_id=snapshot["snapshot_id"],
        reason_code="M38_RECONCILIATION_REQUIRED",
        idempotency_token="m43-alert-001",
        settings_object=settings_for_m43(),
        evaluated_at=NOW,
    )
    alert = service.issue_live_operational_alert(
        db,
        snapshot_id=snapshot["snapshot_id"],
        reason_code="M38_RECONCILIATION_REQUIRED",
        idempotency_token="m43-alert-001",
        confirmation=preview["confirmation"],
        settings_object=settings_for_m43(),
        issued_at=NOW,
    )
    assert alert["status"] == "OPEN"
    assert alert["severity"] == "CRITICAL"
    assert db.query(CanonicalParserLiveOperationalAlert).count() == 1
    assert db.query(CanonicalParserLiveOperationalAlertEvent).count() == 1


def test_active_alert_fingerprint_is_deduplicated(db):
    add_uncertain_submission(db)
    _, snapshot = observe(db)
    first_preview = service.preview_live_operational_alert(
        db,
        snapshot_id=snapshot["snapshot_id"],
        reason_code="M38_RECONCILIATION_REQUIRED",
        idempotency_token="m43-alert-dedup-1",
        settings_object=settings_for_m43(),
        evaluated_at=NOW,
    )
    first = service.issue_live_operational_alert(
        db,
        snapshot_id=snapshot["snapshot_id"],
        reason_code="M38_RECONCILIATION_REQUIRED",
        idempotency_token="m43-alert-dedup-1",
        confirmation=first_preview["confirmation"],
        settings_object=settings_for_m43(),
        issued_at=NOW,
    )
    second_preview = service.preview_live_operational_alert(
        db,
        snapshot_id=snapshot["snapshot_id"],
        reason_code="M38_RECONCILIATION_REQUIRED",
        idempotency_token="m43-alert-dedup-2",
        settings_object=settings_for_m43(),
        evaluated_at=NOW,
    )
    second = service.issue_live_operational_alert(
        db,
        snapshot_id=snapshot["snapshot_id"],
        reason_code="M38_RECONCILIATION_REQUIRED",
        idempotency_token="m43-alert-dedup-2",
        confirmation=second_preview["confirmation"],
        settings_object=settings_for_m43(),
        issued_at=NOW,
    )
    assert first["alert_id"] == second["alert_id"]
    assert db.query(CanonicalParserLiveOperationalAlert).count() == 1


def test_alert_acknowledge_and_resolve_are_audited(db):
    add_uncertain_submission(db)
    _, snapshot = observe(db)
    preview = service.preview_live_operational_alert(
        db,
        snapshot_id=snapshot["snapshot_id"],
        reason_code="M38_RECONCILIATION_REQUIRED",
        idempotency_token="m43-alert-lifecycle",
        settings_object=settings_for_m43(),
        evaluated_at=NOW,
    )
    alert = service.issue_live_operational_alert(
        db,
        snapshot_id=snapshot["snapshot_id"],
        reason_code="M38_RECONCILIATION_REQUIRED",
        idempotency_token="m43-alert-lifecycle",
        confirmation=preview["confirmation"],
        settings_object=settings_for_m43(),
        issued_at=NOW,
    )
    acknowledged = service.acknowledge_live_operational_alert(
        db,
        alert_id=alert["alert_id"],
        confirmation=f"{service.ACK_PREFIX}:{alert['alert_id']}:{alert['evidence_hash']}",
        settings_object=settings_for_m43(),
        acknowledged_at=NOW + timedelta(seconds=1),
    )
    resolved = service.resolve_live_operational_alert(
        db,
        alert_id=alert["alert_id"],
        resolution_evidence="RPC outcome reconciled and verified on-chain",
        confirmation=f"{service.RESOLVE_PREFIX}:{alert['alert_id']}:{alert['evidence_hash']}",
        settings_object=settings_for_m43(),
        resolved_at=NOW + timedelta(seconds=2),
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert resolved["status"] == "RESOLVED"
    assert db.query(CanonicalParserLiveOperationalAlertEvent).count() == 3


def test_observation_requires_enabled_flag(db):
    preview = service.preview_live_operational_observation(
        db,
        idempotency_token="m43-disabled-001",
        settings_object=settings_for_m43(),
        observed_at=NOW,
    )
    with pytest.raises(service.CanonicalParserLiveOperationalObservabilityError) as exc:
        service.observe_live_operations(
            db,
            idempotency_token="m43-disabled-001",
            confirmation=preview["confirmation"],
            settings_object=settings_for_m43(CANONICAL_PARSER_LIVE_OBSERVABILITY_ENABLED=False),
            observed_at=NOW,
        )
    assert exc.value.code == "M43_DISABLED"


def test_snapshot_reason_is_required_for_alert(db):
    _, snapshot = observe(db)
    preview = service.preview_live_operational_alert(
        db,
        snapshot_id=snapshot["snapshot_id"],
        reason_code="M38_RECONCILIATION_REQUIRED",
        idempotency_token="m43-invalid-reason",
        settings_object=settings_for_m43(),
        evaluated_at=NOW,
    )
    assert preview["status"] == "BLOCKED"
    assert "M43_REASON_NOT_IN_SNAPSHOT" in preview["reason_codes"]


def test_m43_openapi_and_static_safety():
    schema = app.openapi()
    required = {
        ("get", "/integrity/parser-live-operational-observability/status"),
        ("post", "/integrity/parser-live-operational-observability/observe"),
        ("post", "/integrity/parser-live-operational-observability/alert/issue"),
        ("post", "/integrity/parser-live-operational-observability/alert/resolve"),
    }
    for method, path in required:
        assert method in schema["paths"][path]
    tree = ast.parse(Path(service.__file__).read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "backend.app.services.solana_transaction_signer" not in imports
    assert "backend.app.services.live_copy_trading_engine" not in imports
    assert "backend.app.workers.helius_live_trading_worker" not in imports

def test_preview_confirmation_remains_valid_across_request_time(db):
    configured = settings_for_m43()

    preview = service.preview_live_operational_observation(
        db,
        idempotency_token="m43-api-confirmation-regression",
        settings_object=configured,
        observed_at=NOW,
    )

    result = service.observe_live_operations(
        db,
        idempotency_token="m43-api-confirmation-regression",
        confirmation=preview["confirmation"],
        settings_object=configured,
        observed_at=NOW + timedelta(seconds=1),
    )

    assert result["status"] == "HEALTHY"
    assert result["snapshot_key"] == preview["snapshot_key"]
    assert (
        db.query(CanonicalParserLiveObservabilitySnapshot).count()
        == 1
    )
