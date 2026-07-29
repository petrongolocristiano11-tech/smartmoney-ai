from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
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
    CanonicalParserLiveIncident,
    CanonicalParserLiveIncidentEvent,
    CanonicalParserLiveRecoveryAuthorization,
)
import backend.app.services.blockchain_parser_live_incident_response_service as service

NOW = datetime(2026, 7, 29, 13, 0, tzinfo=timezone.utc)


def settings_for_m41(**overrides):
    values = {
        "CANONICAL_PARSER_LIVE_INCIDENT_RESPONSE_ENABLED": True,
        "CANONICAL_PARSER_LIVE_INCIDENT_SUBMISSION_GUARD_ENABLED": True,
        "CANONICAL_PARSER_LIVE_INCIDENT_STALE_SUBMISSION_SECONDS": 300,
        "CANONICAL_PARSER_LIVE_INCIDENT_MAX_RECOVERY_VALIDITY_MINUTES": 15,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close(); Base.metadata.drop_all(engine); engine.dispose()


def declare_manual(db: Session, *, token="m41-manual-001", severity="CRITICAL", freeze=True):
    kwargs = dict(source_type="MANUAL", source_id="operator-observation-001", category="RPC_PROVIDER_DEGRADED",
                  severity=severity, freeze_new_submissions=freeze, reason_codes=["RPC_ERROR_RATE_HIGH"],
                  idempotency_token=token, settings_object=settings_for_m41(), evaluated_at=NOW)
    preview = service.preview_live_incident_declaration(db, **kwargs)
    result = service.declare_live_incident(db, **{k: v for k, v in kwargs.items() if k != "evaluated_at"},
                                           confirmation=preview["confirmation"], declared_at=NOW)
    return preview, result


def test_m41_flags_false_by_default():
    configured = Settings(_env_file=None, DATABASE_URL="sqlite+pysqlite:///:memory:", SOLANA_RPC_URL="https://api.mainnet-beta.solana.com", HELIUS_API_KEY="test")
    assert configured.CANONICAL_PARSER_LIVE_INCIDENT_RESPONSE_ENABLED is False
    assert configured.CANONICAL_PARSER_LIVE_INCIDENT_SUBMISSION_GUARD_ENABLED is False


def test_m41_models_registered():
    for table in ("canonical_parser_live_incidents", "canonical_parser_live_incident_events", "canonical_parser_live_recovery_authorizations"):
        assert table in Base.metadata.tables


def test_m41_migration_is_consecutive():
    config = Config("alembic.ini"); config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("d6a8b1c4e520").down_revision == "c5f7a0b3d419"
    assert scripts.get_heads() == ["a9d1e4f7b853"]


def test_manual_incident_is_declared_and_audited(db):
    preview, result = declare_manual(db)
    assert preview["status"] == "READY"
    assert result["status"] == "OPEN"
    assert result["freeze_new_submissions"] is True
    assert db.query(CanonicalParserLiveIncident).count() == 1
    assert db.query(CanonicalParserLiveIncidentEvent).count() == 1


def test_incident_declaration_is_idempotent(db):
    _, first = declare_manual(db)
    _, second = declare_manual(db)
    assert first["incident_id"] == second["incident_id"]
    assert db.query(CanonicalParserLiveIncident).count() == 1


def test_submission_guard_blocks_buy_but_not_sell(db):
    declare_manual(db)
    buy = service.get_live_submission_incident_guard(db, side="BUY", settings_object=settings_for_m41(), evaluated_at=NOW)
    sell = service.get_live_submission_incident_guard(db, side="SELL", settings_object=settings_for_m41(), evaluated_at=NOW)
    assert buy["blocked"] is True
    assert buy["reason_codes"] == ["M41_ACTIVE_INCIDENT_SUBMISSION_FREEZE"]
    assert sell["blocked"] is False


def test_acknowledge_recovery_and_revoke_are_manual(db):
    _, incident = declare_manual(db)
    ack = service.acknowledge_live_incident(
        db, incident_id=incident["incident_id"],
        confirmation=f"{service.ACK_PREFIX}:{incident['incident_id']}:{incident['evidence_hash']}",
        settings_object=settings_for_m41(), acknowledged_at=NOW + timedelta(seconds=1),
    )
    assert ack["status"] == "ACKNOWLEDGED"
    preview = service.preview_live_recovery_authorization(
        db, incident_id=incident["incident_id"], action="FREEZE_NEW_SUBMISSIONS", validity_minutes=5,
        idempotency_token="m41-recovery-001", settings_object=settings_for_m41(), evaluated_at=NOW + timedelta(seconds=2),
    )
    recovery = service.authorize_live_recovery(
        db, incident_id=incident["incident_id"], action="FREEZE_NEW_SUBMISSIONS", validity_minutes=5,
        idempotency_token="m41-recovery-001", confirmation=preview["confirmation"],
        settings_object=settings_for_m41(), issued_at=NOW + timedelta(seconds=2),
    )
    assert recovery["status"] == "ACTIVE"
    revoked = service.revoke_live_recovery(
        db, recovery_id=recovery["recovery_id"],
        confirmation=f"{service.REVOKE_PREFIX}:{recovery['recovery_id']}:{recovery['evidence_hash']}",
        reason="provider stable", settings_object=settings_for_m41(), revoked_at=NOW + timedelta(seconds=3),
    )
    assert revoked["status"] == "REVOKED"
    assert db.query(CanonicalParserLiveRecoveryAuthorization).count() == 1


def test_resolve_clears_submission_freeze(db):
    _, incident = declare_manual(db)
    resolved = service.resolve_live_incident(
        db, incident_id=incident["incident_id"], resolution_evidence="provider metrics healthy for ten minutes",
        confirmation=f"{service.RESOLVE_PREFIX}:{incident['incident_id']}:{incident['evidence_hash']}",
        settings_object=settings_for_m41(), resolved_at=NOW + timedelta(minutes=1),
    )
    assert resolved["status"] == "RESOLVED"
    guard = service.get_live_submission_incident_guard(db, side="BUY", settings_object=settings_for_m41(), evaluated_at=NOW + timedelta(minutes=1))
    assert guard["blocked"] is False


def test_declare_requires_enabled_flag(db):
    preview = service.preview_live_incident_declaration(
        db, source_type="MANUAL", source_id="manual-disabled", severity="HIGH", freeze_new_submissions=True,
        category="MANUAL", reason_codes=[], idempotency_token="m41-disabled", settings_object=settings_for_m41(), evaluated_at=NOW,
    )
    with pytest.raises(service.CanonicalParserLiveIncidentResponseError) as exc:
        service.declare_live_incident(
            db, source_type="MANUAL", source_id="manual-disabled", severity="HIGH", freeze_new_submissions=True,
            category="MANUAL", reason_codes=[], idempotency_token="m41-disabled", confirmation=preview["confirmation"],
            settings_object=settings_for_m41(CANONICAL_PARSER_LIVE_INCIDENT_RESPONSE_ENABLED=False), declared_at=NOW,
        )
    assert exc.value.code == "M41_DISABLED"


def test_m41_openapi_and_static_safety():
    schema = app.openapi()
    required = {
        ("get", "/integrity/parser-live-incident-response/status"),
        ("post", "/integrity/parser-live-incident-response/declare"),
        ("post", "/integrity/parser-live-incident-response/recovery/authorize"),
        ("post", "/integrity/parser-live-incident-response/resolve"),
    }
    for method, path in required:
        assert method in schema["paths"][path]
    tree = ast.parse(Path(service.__file__).read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "backend.app.services.solana_transaction_signer" not in imports
    assert "backend.app.services.live_copy_trading_engine" not in imports
    assert "backend.app.workers.helius_live_trading_worker" not in imports
