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
    CanonicalParserPaperProjectionReadinessAssessment,
    CanonicalParserPaperProjectionReadinessEvidenceRun,
    CanonicalParserPaperProjectionResult,
    CanonicalParserPaperProjectionRun,
    CanonicalParserShadowReliabilityAssessment,
    CanonicalParserShadowReliabilityCertification,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
import backend.app.services.blockchain_parser_paper_projection_readiness_service as M25

NOW = datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc)
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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_ENABLED", False)


def _settings_values(**overrides):
    values = {"DATABASE_URL": "sqlite+pysqlite:///:memory:", "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com", "HELIUS_API_KEY": "test"}
    values.update(overrides)
    return values


def _policy(enabled=True, *, min_runs=3, min_results=3, min_rate=100.0, max_review=0, max_rejected=0, min_observation=5, validity=30):
    return SimpleNamespace(
        CANONICAL_PARSER_PAPER_PROJECTION_READINESS_ENABLED=enabled,
        CANONICAL_PARSER_PAPER_PROJECTION_READINESS_LOOKBACK_MINUTES=1440,
        CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MAX_SOURCE_RUNS=20,
        CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_RUNS=min_runs,
        CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_RESULTS=min_results,
        CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_PROJECTABLE_RATE=min_rate,
        CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MAX_REVIEW_RESULTS=max_review,
        CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MAX_REJECTED_RESULTS=max_rejected,
        CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_OBSERVATION_MINUTES=min_observation,
        CANONICAL_PARSER_PAPER_PROJECTION_READINESS_VALIDITY_MINUTES=validity,
    )


def _certification(db):
    assessment = CanonicalParserShadowReliabilityAssessment(
        assessment_id=str(uuid4()), assessment_key=calculate_payload_hash({"assessment": str(uuid4())}),
        worker_state_db_id=None, worker_generation=3, lease_epoch=7, worker_event_hash="1" * 64,
        status="READY", loop_count=3, completed_iteration_count=12, passed_iteration_count=12,
        partial_iteration_count=0, idle_iteration_count=0, failed_iteration_count=0,
        skipped_iteration_count=0, circuit_open_count=0, recovery_run_count=0,
        recovery_action_count=0, pass_rate=100, observation_started_at=NOW-timedelta(minutes=20),
        observation_completed_at=NOW-timedelta(minutes=10), reason_codes=[], policy_version="m22",
        policy_hash=calculate_payload_hash({"m22": 1}), policy_snapshot={"m22": 1},
        evidence_hash=calculate_payload_hash({"evidence": 1}), evidence_snapshot={"evidence": 1},
        metrics_snapshot={"pass_rate": 100}, actor_label="TEST", note=None,
        evaluated_at=NOW-timedelta(minutes=10), valid_until=NOW+timedelta(minutes=15),
    )
    db.add(assessment); db.flush()
    cert = CanonicalParserShadowReliabilityCertification(
        certification_id=str(uuid4()), certification_key=calculate_payload_hash({"cert": str(uuid4())}),
        assessment_db_id=assessment.id, assessment_id=assessment.assessment_id,
        assessment_key=assessment.assessment_key, worker_generation=assessment.worker_generation,
        lease_epoch=assessment.lease_epoch, worker_event_hash=assessment.worker_event_hash,
        status="ACTIVE", evidence_hash=assessment.evidence_hash, policy_version="m23",
        policy_hash=calculate_payload_hash({"m23": 1}), policy_snapshot={"m23": 1},
        actor_label="TEST", note=None, certified_at=NOW-timedelta(minutes=10),
        expires_at=NOW+timedelta(minutes=60), revoked_at=None, revocation_reason=None,
        latest_event_sequence=1, latest_event_hash="3" * 64,
        technical_metadata={"paper_execution_authorized": False},
    )
    db.add(cert); db.commit(); return cert


def _resolved(cert, status="CERTIFIED"):
    return {
        "resolved_status": status,
        "certification_id": cert.certification_id,
        "assessment_id": cert.assessment_id,
        "latest_event_hash": cert.latest_event_hash,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _projection(db, cert, *, completed_at, status="PASSED", result_statuses=("PROJECTABLE",)):
    counts = {name: sum(value == name for value in result_statuses) for name in ("PROJECTABLE", "REVIEW", "REJECTED")}
    run = CanonicalParserPaperProjectionRun(
        projection_id=str(uuid4()), projection_key=calculate_payload_hash({"projection": str(uuid4())}),
        certification_db_id=cert.id, certification_id=cert.certification_id,
        certification_event_hash=cert.latest_event_hash, assessment_id=cert.assessment_id,
        source_run_count=1, source_result_count=len(result_statuses),
        projectable_count=counts["PROJECTABLE"], review_count=counts["REVIEW"], rejected_count=counts["REJECTED"],
        status=status, policy_version="m24", policy_hash=calculate_payload_hash({"m24": 1}),
        policy_snapshot={"m24": 1}, source_evidence_hash=calculate_payload_hash({"source": str(uuid4())}),
        source_snapshot={}, metrics_snapshot={}, reason_codes=[], actor_label="TEST", note=None,
        started_at=completed_at-timedelta(minutes=1), completed_at=completed_at,
    )
    db.add(run); db.flush()
    for sequence, result_status in enumerate(result_statuses, start=1):
        db.add(CanonicalParserPaperProjectionResult(
            result_id=str(uuid4()), projection_run_db_id=run.id, sequence=sequence,
            source_execution_run_db_id=1000+run.id, source_execution_run_id=str(uuid4()),
            source_result_db_id=2000+run.id*10+sequence, source_result_id=str(uuid4()),
            raw_event_id=3000+sequence, artifact_index=sequence-1, status=result_status,
            action="BUY", wallet_address="W"*44, token_mint="T"*44,
            token_amount="10", sol_amount="0.1", artifact_hash=calculate_payload_hash({"artifact": str(uuid4())}),
            projection_hash=calculate_payload_hash({"result": str(uuid4())}),
            projection_payload={"paper_execution": False}, reason_codes=[],
        ))
    db.commit(); return run


def _client(factory):
    def override_db():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m25_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_PAPER_PROJECTION_READINESS_ENABLED is False
    assert configured.CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_RUNS == 3


def test_m25_preview_blocked_without_certification(db_factory, monkeypatch):
    with db_factory() as db:
        monkeypatch.setattr(M25, "resolve_shadow_reliability_certification", lambda *a, **k: {"resolved_status": "UNCERTIFIED"})
        preview = M25.preview_paper_projection_readiness(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "BLOCKED"
        assert preview["paper_execution_authorized"] is False


def test_m25_preview_insufficient_without_runs(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db)
        monkeypatch.setattr(M25, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        preview = M25.preview_paper_projection_readiness(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "INSUFFICIENT_DATA"


def test_m25_preview_ready_with_clean_evidence(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db)
        for minute in (12, 6, 1): _projection(db, cert, completed_at=NOW-timedelta(minutes=minute))
        monkeypatch.setattr(M25, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        preview = M25.preview_paper_projection_readiness(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "READY"
        assert preview["metrics"]["projectable_rate"] == 100.0


def test_m25_preview_review_for_review_results(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db)
        _projection(db, cert, completed_at=NOW-timedelta(minutes=12))
        _projection(db, cert, completed_at=NOW-timedelta(minutes=6))
        _projection(db, cert, completed_at=NOW-timedelta(minutes=1), status="PARTIAL", result_statuses=("PROJECTABLE", "REVIEW"))
        monkeypatch.setattr(M25, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        assert M25.preview_paper_projection_readiness(db, settings_object=_policy(), evaluated_at=NOW)["status"] == "REVIEW"


def test_m25_preview_blocked_for_rejected_results(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db)
        _projection(db, cert, completed_at=NOW-timedelta(minutes=12))
        _projection(db, cert, completed_at=NOW-timedelta(minutes=6))
        _projection(db, cert, completed_at=NOW-timedelta(minutes=1), status="PARTIAL", result_statuses=("REJECTED",))
        monkeypatch.setattr(M25, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        assert M25.preview_paper_projection_readiness(db, settings_object=_policy(), evaluated_at=NOW)["status"] == "BLOCKED"


def test_m25_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(M25.CanonicalParserPaperProjectionReadinessError) as error:
            M25.execute_paper_projection_readiness_assessment(db, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_DISABLED"


def test_m25_persistence_and_idempotency(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db)
        for minute in (12, 6, 1): _projection(db, cert, completed_at=NOW-timedelta(minutes=minute))
        monkeypatch.setattr(M25, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        preview = M25.preview_paper_projection_readiness(db, settings_object=_policy(), evaluated_at=NOW)
        first = M25.execute_paper_projection_readiness_assessment(db, confirmation=preview["confirmation"], settings_object=_policy(), evaluated_at=NOW)
        second = M25.execute_paper_projection_readiness_assessment(db, confirmation=preview["confirmation"], settings_object=_policy(), evaluated_at=NOW)
        assert first["assessment_id"] == second["assessment_id"]
        assert db.query(CanonicalParserPaperProjectionReadinessAssessment).count() == 1
        assert db.query(CanonicalParserPaperProjectionReadinessEvidenceRun).count() == 3


def test_m25_resolve_ready_then_drifted(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db)
        for minute in (12, 6, 1): _projection(db, cert, completed_at=NOW-timedelta(minutes=minute))
        monkeypatch.setattr(M25, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        preview = M25.preview_paper_projection_readiness(db, settings_object=_policy(), evaluated_at=NOW)
        M25.execute_paper_projection_readiness_assessment(db, confirmation=preview["confirmation"], settings_object=_policy(), evaluated_at=NOW)
        assert M25.resolve_paper_projection_readiness(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "READY"
        _projection(db, cert, completed_at=NOW, status="PARTIAL", result_statuses=("REVIEW",))
        assert M25.resolve_paper_projection_readiness(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "DRIFTED"


def test_m25_resolve_expired(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db)
        for minute in (12, 6, 1): _projection(db, cert, completed_at=NOW-timedelta(minutes=minute))
        monkeypatch.setattr(M25, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        policy = _policy(validity=1)
        preview = M25.preview_paper_projection_readiness(db, settings_object=policy, evaluated_at=NOW)
        M25.execute_paper_projection_readiness_assessment(db, confirmation=preview["confirmation"], settings_object=policy, evaluated_at=NOW)
        assert M25.resolve_paper_projection_readiness(db, settings_object=policy, evaluated_at=NOW+timedelta(minutes=2))["resolved_status"] == "EXPIRED"


def test_m25_status_counts(db_factory):
    with db_factory() as db:
        status = M25.get_paper_projection_readiness_status(db, settings_object=_policy(False))
        assert status["assessment_count"] == 0
        assert status["operational_guards"]["paper_order_writes"] is False


def test_m25_endpoint_requires_key_and_is_registered(db_factory):
    client = _client(db_factory)
    try:
        path = "/integrity/parser-paper-projection-readiness/status"
        assert client.get(path).status_code in {401, 403}
        response = client.get(path, headers={"X-Automation-Key": AUTOMATION_KEY})
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()


def test_m25_model_metadata_registered():
    assert "canonical_parser_paper_projection_readiness_assessments" in Base.metadata.tables
    assert "canonical_parser_paper_projection_readiness_evidence_runs" in Base.metadata.tables
