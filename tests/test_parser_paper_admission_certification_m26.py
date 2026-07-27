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
    CanonicalParserPaperAdmissionCertification,
    CanonicalParserPaperAdmissionCertificationEvent,
    CanonicalParserPaperProjectionReadinessAssessment,
    CanonicalParserShadowReliabilityAssessment,
    CanonicalParserShadowReliabilityCertification,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
import backend.app.services.blockchain_parser_paper_admission_certification_service as M26

NOW = datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc)
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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_ENABLED", False)


def _settings_values(**overrides):
    values = {"DATABASE_URL": "sqlite+pysqlite:///:memory:", "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com", "HELIUS_API_KEY": "test"}
    values.update(overrides)
    return values


def _policy(enabled=True, validity=60):
    return SimpleNamespace(
        CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_ENABLED=enabled,
        CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_VALIDITY_MINUTES=validity,
    )


def _readiness(db):
    reliability = CanonicalParserShadowReliabilityAssessment(
        assessment_id=str(uuid4()), assessment_key=calculate_payload_hash({"m22": str(uuid4())}),
        worker_state_db_id=None, worker_generation=1, lease_epoch=1, worker_event_hash="1"*64,
        status="READY", loop_count=3, completed_iteration_count=10, passed_iteration_count=10,
        partial_iteration_count=0, idle_iteration_count=0, failed_iteration_count=0, skipped_iteration_count=0,
        circuit_open_count=0, recovery_run_count=0, recovery_action_count=0, pass_rate=100,
        observation_started_at=NOW-timedelta(minutes=20), observation_completed_at=NOW-timedelta(minutes=10),
        reason_codes=[], policy_version="m22", policy_hash="2"*64, policy_snapshot={}, evidence_hash="3"*64,
        evidence_snapshot={}, metrics_snapshot={}, actor_label="TEST", note=None,
        evaluated_at=NOW-timedelta(minutes=10), valid_until=NOW+timedelta(minutes=30),
    )
    db.add(reliability); db.flush()
    cert = CanonicalParserShadowReliabilityCertification(
        certification_id=str(uuid4()), certification_key=calculate_payload_hash({"m23": str(uuid4())}),
        assessment_db_id=reliability.id, assessment_id=reliability.assessment_id,
        assessment_key=reliability.assessment_key, worker_generation=1, lease_epoch=1, worker_event_hash="1"*64,
        status="ACTIVE", evidence_hash="3"*64, policy_version="m23", policy_hash="4"*64, policy_snapshot={},
        actor_label="TEST", note=None, certified_at=NOW-timedelta(minutes=8), expires_at=NOW+timedelta(minutes=60),
        revoked_at=None, revocation_reason=None, latest_event_sequence=1, latest_event_hash="5"*64, technical_metadata={},
    )
    db.add(cert); db.flush()
    assessment = CanonicalParserPaperProjectionReadinessAssessment(
        assessment_id=str(uuid4()), assessment_key=calculate_payload_hash({"m25": str(uuid4())}),
        certification_db_id=cert.id, certification_id=cert.certification_id,
        certification_event_hash=cert.latest_event_hash, status="READY", run_count=3, result_count=3,
        projectable_count=3, review_count=0, rejected_count=0, projectable_rate=100,
        observation_started_at=NOW-timedelta(minutes=10), observation_completed_at=NOW-timedelta(minutes=1),
        policy_version="m25", policy_hash="6"*64, policy_snapshot={}, evidence_hash="7"*64,
        evidence_snapshot={}, metrics_snapshot={}, reason_codes=[], actor_label="TEST", note=None,
        evaluated_at=NOW-timedelta(minutes=1), valid_until=NOW+timedelta(minutes=30),
    )
    db.add(assessment); db.commit(); return assessment


def _resolved(assessment, status="READY"):
    return {
        "resolved_status": status,
        "assessment_id": assessment.assessment_id,
        "assessment_key": assessment.assessment_key,
        "certification_id": assessment.certification_id,
        "certification_event_hash": assessment.certification_event_hash,
        "evidence_hash": assessment.evidence_hash,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _client(factory):
    def override_db():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _certify(db, monkeypatch, *, policy=None):
    assessment = _readiness(db)
    monkeypatch.setattr(M26, "resolve_paper_projection_readiness", lambda *a, **k: _resolved(assessment))
    policy = policy or _policy()
    preview = M26.preview_paper_admission_certification(db, settings_object=policy, evaluated_at=NOW)
    result = M26.certify_paper_admission(db, confirmation=preview["confirmation"], settings_object=policy, certified_at=NOW)
    return assessment, result


def test_m26_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_ENABLED is False
    assert configured.CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_VALIDITY_MINUTES == 60


def test_m26_preview_blocked_without_ready_assessment(db_factory, monkeypatch):
    with db_factory() as db:
        monkeypatch.setattr(M26, "resolve_paper_projection_readiness", lambda *a, **k: {"resolved_status": "UNASSESSED"})
        preview = M26.preview_paper_admission_certification(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["eligible"] is False
        assert preview["paper_execution_authorized"] is False


def test_m26_preview_eligible_for_ready_assessment(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _readiness(db)
        monkeypatch.setattr(M26, "resolve_paper_projection_readiness", lambda *a, **k: _resolved(assessment))
        preview = M26.preview_paper_admission_certification(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["eligible"] is True
        assert preview["paper_runtime_connected"] is False


def test_m26_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(M26.CanonicalParserPaperAdmissionCertificationError) as error:
            M26.certify_paper_admission(db, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_DISABLED"


def test_m26_persistence_and_idempotency(db_factory, monkeypatch):
    with db_factory() as db:
        assessment = _readiness(db)
        monkeypatch.setattr(M26, "resolve_paper_projection_readiness", lambda *a, **k: _resolved(assessment))
        preview = M26.preview_paper_admission_certification(db, settings_object=_policy(), evaluated_at=NOW)
        first = M26.certify_paper_admission(db, confirmation=preview["confirmation"], settings_object=_policy(), certified_at=NOW)
        second = M26.certify_paper_admission(db, confirmation=preview["confirmation"], settings_object=_policy(), certified_at=NOW)
        assert first["certification_id"] == second["certification_id"]
        assert db.query(CanonicalParserPaperAdmissionCertification).count() == 1
        assert db.query(CanonicalParserPaperAdmissionCertificationEvent).count() == 1
        assert first["paper_execution_authorized"] is False


def test_m26_resolve_certified(db_factory, monkeypatch):
    with db_factory() as db:
        assessment, result = _certify(db, monkeypatch)
        monkeypatch.setattr(M26, "resolve_paper_projection_readiness", lambda *a, **k: _resolved(assessment))
        resolved = M26.resolve_paper_admission_certification(db, settings_object=_policy(), evaluated_at=NOW)
        assert resolved["resolved_status"] == "CERTIFIED"
        assert resolved["paper_admission_certified"] is True
        assert resolved["paper_execution_authorized"] is False


def test_m26_resolve_expired(db_factory, monkeypatch):
    with db_factory() as db:
        policy = _policy(validity=1)
        assessment, _ = _certify(db, monkeypatch, policy=policy)
        monkeypatch.setattr(M26, "resolve_paper_projection_readiness", lambda *a, **k: _resolved(assessment))
        assert M26.resolve_paper_admission_certification(db, settings_object=policy, evaluated_at=NOW+timedelta(minutes=2))["resolved_status"] == "EXPIRED"


def test_m26_resolve_drifted(db_factory, monkeypatch):
    with db_factory() as db:
        assessment, _ = _certify(db, monkeypatch)
        monkeypatch.setattr(M26, "resolve_paper_projection_readiness", lambda *a, **k: {**_resolved(assessment), "evidence_hash": "9"*64})
        assert M26.resolve_paper_admission_certification(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "DRIFTED"


def test_m26_revoke_is_audited_and_idempotent(db_factory, monkeypatch):
    with db_factory() as db:
        _, result = _certify(db, monkeypatch)
        confirmation = f"{M26.PAPER_ADMISSION_CERTIFICATION_REVOKE_PREFIX}:{result['certification_id']}"
        first = M26.revoke_paper_admission_certification(db, certification_id=result["certification_id"], confirmation=confirmation, reason="operator stop", revoked_at=NOW)
        second = M26.revoke_paper_admission_certification(db, certification_id=result["certification_id"], confirmation=confirmation, reason="operator stop", revoked_at=NOW)
        assert first["status"] == second["status"] == "REVOKED"
        assert db.query(CanonicalParserPaperAdmissionCertificationEvent).count() == 2


def test_m26_audit_tamper_is_detected(db_factory, monkeypatch):
    with db_factory() as db:
        assessment, _ = _certify(db, monkeypatch)
        event = db.query(CanonicalParserPaperAdmissionCertificationEvent).one()
        event.event_hash = "0"*64; db.commit()
        monkeypatch.setattr(M26, "resolve_paper_projection_readiness", lambda *a, **k: _resolved(assessment))
        assert M26.resolve_paper_admission_certification(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "AUDIT_INVALID"


def test_m26_get_not_found(db_factory):
    with db_factory() as db:
        with pytest.raises(M26.CanonicalParserPaperAdmissionCertificationError) as error:
            M26.get_paper_admission_certification(db, str(uuid4()))
        assert error.value.status_code == 404


def test_m26_status_counts(db_factory):
    with db_factory() as db:
        status = M26.get_paper_admission_certification_status(db, settings_object=_policy(False))
        assert status["certification_count"] == 0
        assert status["operational_guards"]["paper_runtime_connected"] is False


def test_m26_endpoint_requires_key_and_is_registered(db_factory):
    client = _client(db_factory)
    try:
        path = "/integrity/parser-paper-admission-certification/status"
        assert client.get(path).status_code in {401, 403}
        response = client.get(path, headers={"X-Automation-Key": AUTOMATION_KEY})
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()


def test_m26_model_metadata_registered():
    assert "canonical_parser_paper_admission_certifications" in Base.metadata.tables
    assert "canonical_parser_paper_admission_certification_events" in Base.metadata.tables
