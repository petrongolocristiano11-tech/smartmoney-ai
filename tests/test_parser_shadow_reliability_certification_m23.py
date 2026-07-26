from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.core.config import Settings, settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowReliabilityAssessment,
    CanonicalParserShadowReliabilityCertification,
    CanonicalParserShadowReliabilityCertificationEvent,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
import backend.app.services.blockchain_parser_shadow_reliability_certification_service as M23

NOW = datetime(2026, 7, 26, 23, 0, tzinfo=timezone.utc)
AUTOMATION_KEY = "a" * 32


@pytest.fixture()
def db_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def safe_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_ENABLED", False)


def _settings_values(**overrides):
    values = {"DATABASE_URL": "sqlite+pysqlite:///:memory:", "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com", "HELIUS_API_KEY": "test"}
    values.update(overrides)
    return values


def _policy(enabled=True, validity=60):
    return SimpleNamespace(
        CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_ENABLED=enabled,
        CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_VALIDITY_MINUTES=validity,
    )


def _assessment(db):
    item = CanonicalParserShadowReliabilityAssessment(
        assessment_id=str(uuid4()), assessment_key=calculate_payload_hash({"assessment": "m23"}),
        worker_state_db_id=None, worker_generation=3, lease_epoch=7, worker_event_hash="1" * 64,
        status="READY", loop_count=3, completed_iteration_count=12, passed_iteration_count=12,
        partial_iteration_count=0, idle_iteration_count=0, failed_iteration_count=0,
        skipped_iteration_count=0, circuit_open_count=0, recovery_run_count=0,
        recovery_action_count=0, pass_rate=100, observation_started_at=NOW-timedelta(minutes=10),
        observation_completed_at=NOW-timedelta(minutes=1), reason_codes=[], policy_version="m22",
        policy_hash=calculate_payload_hash({"m22": 1}), policy_snapshot={"m22": 1},
        evidence_hash=calculate_payload_hash({"evidence": 1}), evidence_snapshot={"evidence": 1},
        metrics_snapshot={"pass_rate": 100}, actor_label="TEST", note=None,
        evaluated_at=NOW-timedelta(minutes=1), valid_until=NOW+timedelta(minutes=15),
    )
    db.add(item); db.commit(); return item


def _resolved(item, *, status="READY", evidence_hash=None):
    return {
        "resolved_status": status,
        "assessment_id": item.assessment_id,
        "assessment_key": item.assessment_key,
        "worker_generation": item.worker_generation,
        "lease_epoch": item.lease_epoch,
        "worker_event_hash": item.worker_event_hash,
        "evidence_hash": evidence_hash or item.evidence_hash,
    }


def _client(factory):
    def override_db():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m23_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_ENABLED is False
    assert configured.CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_VALIDITY_MINUTES == 60


def test_m23_preview_blocked_without_ready_assessment(db_factory, monkeypatch):
    with db_factory() as db:
        monkeypatch.setattr(M23, "resolve_shadow_reliability", lambda *a, **k: {"resolved_status": "UNASSESSED"})
        preview = M23.preview_shadow_reliability_certification(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["eligible"] is False
        assert "SHADOW_RELIABILITY_NOT_READY" in preview["reason_codes"]


def test_m23_preview_eligible_for_ready_assessment(db_factory, monkeypatch):
    with db_factory() as db:
        item = _assessment(db)
        monkeypatch.setattr(M23, "resolve_shadow_reliability", lambda *a, **k: _resolved(item))
        preview = M23.preview_shadow_reliability_certification(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["eligible"] is True
        assert preview["paper_execution_authorized"] is False


def test_m23_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(M23.CanonicalParserShadowReliabilityCertificationError) as error:
            M23.certify_shadow_reliability(db, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_DISABLED"


def test_m23_confirmation_required(db_factory, monkeypatch):
    with db_factory() as db:
        item = _assessment(db)
        monkeypatch.setattr(M23, "resolve_shadow_reliability", lambda *a, **k: _resolved(item))
        with pytest.raises(M23.CanonicalParserShadowReliabilityCertificationError) as error:
            M23.certify_shadow_reliability(db, confirmation="bad", settings_object=_policy(), certified_at=NOW)
        assert error.value.code == "SHADOW_RELIABILITY_CERTIFICATION_CONFIRMATION_REQUIRED"


def test_m23_persistence_idempotency_and_event_chain(db_factory, monkeypatch):
    with db_factory() as db:
        item = _assessment(db)
        monkeypatch.setattr(M23, "resolve_shadow_reliability", lambda *a, **k: _resolved(item))
        preview = M23.preview_shadow_reliability_certification(db, settings_object=_policy(), evaluated_at=NOW)
        first = M23.certify_shadow_reliability(db, confirmation=preview["confirmation"], settings_object=_policy(), certified_at=NOW)
        second = M23.certify_shadow_reliability(db, confirmation=preview["confirmation"], settings_object=_policy(), certified_at=NOW)
        assert first["certification_id"] == second["certification_id"]
        assert db.query(CanonicalParserShadowReliabilityCertification).count() == 1
        assert db.query(CanonicalParserShadowReliabilityCertificationEvent).count() == 1
        loaded = M23.get_shadow_reliability_certification(db, first["certification_id"])
        assert loaded["event_chain_reason_codes"] == []


def test_m23_resolve_certified(db_factory, monkeypatch):
    with db_factory() as db:
        item = _assessment(db)
        monkeypatch.setattr(M23, "resolve_shadow_reliability", lambda *a, **k: _resolved(item))
        preview = M23.preview_shadow_reliability_certification(db, settings_object=_policy(), evaluated_at=NOW)
        M23.certify_shadow_reliability(db, confirmation=preview["confirmation"], settings_object=_policy(), certified_at=NOW)
        resolved = M23.resolve_shadow_reliability_certification(db, settings_object=_policy(), evaluated_at=NOW)
        assert resolved["resolved_status"] == "CERTIFIED"
        assert resolved["paper_projection_authorized"] is True
        assert resolved["paper_execution_authorized"] is False


def test_m23_resolve_expired(db_factory, monkeypatch):
    with db_factory() as db:
        item = _assessment(db)
        monkeypatch.setattr(M23, "resolve_shadow_reliability", lambda *a, **k: _resolved(item))
        preview = M23.preview_shadow_reliability_certification(db, settings_object=_policy(validity=1), evaluated_at=NOW)
        M23.certify_shadow_reliability(db, confirmation=preview["confirmation"], settings_object=_policy(validity=1), certified_at=NOW)
        assert M23.resolve_shadow_reliability_certification(db, settings_object=_policy(validity=1), evaluated_at=NOW+timedelta(minutes=2))["resolved_status"] == "EXPIRED"


def test_m23_resolve_drifted_when_evidence_changes(db_factory, monkeypatch):
    with db_factory() as db:
        item = _assessment(db)
        monkeypatch.setattr(M23, "resolve_shadow_reliability", lambda *a, **k: _resolved(item))
        preview = M23.preview_shadow_reliability_certification(db, settings_object=_policy(), evaluated_at=NOW)
        M23.certify_shadow_reliability(db, confirmation=preview["confirmation"], settings_object=_policy(), certified_at=NOW)
        monkeypatch.setattr(M23, "resolve_shadow_reliability", lambda *a, **k: _resolved(item, evidence_hash="2"*64))
        assert M23.resolve_shadow_reliability_certification(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "DRIFTED"


def test_m23_revoke_is_audited_and_idempotent(db_factory, monkeypatch):
    with db_factory() as db:
        item = _assessment(db)
        monkeypatch.setattr(M23, "resolve_shadow_reliability", lambda *a, **k: _resolved(item))
        preview = M23.preview_shadow_reliability_certification(db, settings_object=_policy(), evaluated_at=NOW)
        cert = M23.certify_shadow_reliability(db, confirmation=preview["confirmation"], settings_object=_policy(), certified_at=NOW)
        confirmation = f"{M23.SHADOW_RELIABILITY_CERTIFICATION_REVOKE_PREFIX}:{cert['certification_id']}"
        first = M23.revoke_shadow_reliability_certification(db, certification_id=cert["certification_id"], confirmation=confirmation, reason="manual stop", revoked_at=NOW)
        second = M23.revoke_shadow_reliability_certification(db, certification_id=cert["certification_id"], confirmation=confirmation, reason="manual stop", revoked_at=NOW)
        assert first["status"] == second["status"] == "REVOKED"
        assert db.query(CanonicalParserShadowReliabilityCertificationEvent).count() == 2
        assert M23.resolve_shadow_reliability_certification(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "REVOKED"


def test_m23_status_counts(db_factory, monkeypatch):
    with db_factory() as db:
        item = _assessment(db)
        monkeypatch.setattr(M23, "resolve_shadow_reliability", lambda *a, **k: _resolved(item))
        preview = M23.preview_shadow_reliability_certification(db, settings_object=_policy(), evaluated_at=NOW)
        M23.certify_shadow_reliability(db, confirmation=preview["confirmation"], settings_object=_policy(), certified_at=NOW)
        status = M23.get_shadow_reliability_certification_status(db, settings_object=_policy())
        assert status["certification_count"] == 1
        assert status["event_count"] == 1
        assert status["operational_guards"]["paper_execution_authorized"] is False


def test_m23_endpoint_requires_key_and_is_registered(db_factory):
    client = _client(db_factory)
    try:
        path = "/integrity/parser-shadow-reliability-certification/status"
        assert client.get(path).status_code in {401, 403}
        response = client.get(path, headers={"X-Automation-Key": AUTOMATION_KEY})
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()


def test_m23_model_metadata_registered():
    assert "canonical_parser_shadow_reliability_certifications" in Base.metadata.tables
    assert "canonical_parser_shadow_reliability_certification_events" in Base.metadata.tables
