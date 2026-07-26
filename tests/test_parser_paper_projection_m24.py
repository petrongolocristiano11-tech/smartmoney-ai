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
    CanonicalParserPaperProjectionResult,
    CanonicalParserPaperProjectionRun,
    CanonicalParserShadowReliabilityAssessment,
    CanonicalParserShadowReliabilityCertification,
    CanonicalParserShadowTicketExecutionResult,
    CanonicalParserShadowTicketExecutionRun,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
import backend.app.services.blockchain_parser_paper_projection_service as M24

NOW = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)
AUTOMATION_KEY = "a" * 32
WALLET = "W" * 44
TOKEN = "T" * 44


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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_PAPER_PROJECTION_ENABLED", False)


def _settings_values(**overrides):
    values = {"DATABASE_URL": "sqlite+pysqlite:///:memory:", "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com", "HELIUS_API_KEY": "test"}
    values.update(overrides)
    return values


def _policy(enabled=True, min_projectable=1):
    return SimpleNamespace(
        CANONICAL_PARSER_PAPER_PROJECTION_ENABLED=enabled,
        CANONICAL_PARSER_PAPER_PROJECTION_LOOKBACK_MINUTES=1440,
        CANONICAL_PARSER_PAPER_PROJECTION_MAX_SOURCE_RUNS=10,
        CANONICAL_PARSER_PAPER_PROJECTION_MAX_ARTIFACTS=100,
        CANONICAL_PARSER_PAPER_PROJECTION_MIN_PROJECTABLE_RESULTS=min_projectable,
    )


def _assessment(db):
    item = CanonicalParserShadowReliabilityAssessment(
        assessment_id=str(uuid4()), assessment_key=calculate_payload_hash({"assessment": "m24"}),
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


def _certification(db):
    assessment = _assessment(db)
    cert = CanonicalParserShadowReliabilityCertification(
        certification_id=str(uuid4()), certification_key=calculate_payload_hash({"cert": "m24"}),
        assessment_db_id=assessment.id, assessment_id=assessment.assessment_id,
        assessment_key=assessment.assessment_key, worker_generation=assessment.worker_generation,
        lease_epoch=assessment.lease_epoch, worker_event_hash=assessment.worker_event_hash,
        status="ACTIVE", evidence_hash=assessment.evidence_hash, policy_version="m23",
        policy_hash=calculate_payload_hash({"m23": 1}), policy_snapshot={"m23": 1},
        actor_label="TEST", note=None, certified_at=NOW-timedelta(minutes=2),
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
        "paper_projection_authorized": status == "CERTIFIED",
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _artifact(*, side="BUY", quality="PASS", success=True, token=TOKEN, wallet=WALLET, token_amount="250", sol_amount="0.125"):
    payload = {
        "canonical_type": "SWAP", "schema_version": "canonical-swap/1",
        "signature": "sig", "wallet_address": wallet, "side": side,
        "source": "JUPITER", "token_mint": token, "token_amount": token_amount,
        "sol_amount": sol_amount, "success": success, "quality_status": quality,
        "quality_flags": [], "raw_transaction_hash": "4" * 64,
    }
    return {
        "artifact_type": "CANONICAL_SWAP_EVENT", "artifact_index": 0,
        "schema_version": "canonical-swap/1", "payload": payload,
        "payload_hash": calculate_payload_hash(payload), "artifact_metadata": {"deterministic": True},
    }


def _source(db, artifacts, *, run_status="PASSED"):
    run = CanonicalParserShadowTicketExecutionRun(
        run_id=str(uuid4()), run_key=calculate_payload_hash({"run": str(uuid4())}),
        ticket_db_id=(db.query(CanonicalParserShadowTicketExecutionRun).count() + 1), ticket_id=str(uuid4()), ticket_key="5"*64,
        permit_db_id=1, permit_id=str(uuid4()), assessment_id=str(uuid4()),
        lease_id=str(uuid4()), certification_id=str(uuid4()), binding_id=str(uuid4()), promotion_id=str(uuid4()),
        scope="SHADOW_ONLY", channel="CANONICAL_SHADOW", consumer="CERTIFIED_SHADOW_AUTOMATION",
        executor="CERTIFIED_SHADOW_TICKET_EXECUTION", status=run_status,
        parser_name="swap_canonical_event", parser_version="1.0.0", parser_implementation_hash="6"*64,
        output_schema_version="canonical-swap/1", release_manifest_hash="7"*64,
        readiness_evidence_hash="8"*64, permit_policy_hash="9"*64, permit_event_hash="a"*64,
        ticket_policy_hash="b"*64, ticket_event_hash="c"*64,
        execution_policy_version="m16", execution_policy_hash="d"*64,
        execution_policy_snapshot={}, requested_limit=10, reserved_run_count=1, reserved_event_count=1,
        selected_count=1, processed_count=1, passed_count=1, failed_count=0, skipped_count=0,
        artifact_count=len(artifacts), consumed_run_count=1, consumed_event_count=1,
        released_event_count=0, budget_settled=True, settlement_hash="e"*64,
        actor_label="TEST", note=None, reason_codes=[], selection_snapshot={}, metrics_snapshot={},
        technical_metadata={"paper_execution": False}, started_at=NOW-timedelta(minutes=5), completed_at=NOW-timedelta(minutes=4),
    )
    db.add(run); db.flush()
    result = CanonicalParserShadowTicketExecutionResult(
        result_id=str(uuid4()), execution_run_db_id=run.id, raw_event_id=101,
        raw_payload_hash="f"*64, status="PASS", compatible=True, deterministic=True,
        output_hash=calculate_payload_hash(artifacts), verification_output_hash=calculate_payload_hash(artifacts),
        artifact_count=len(artifacts), shadow_artifacts=artifacts, reason_codes=[], error_message=None,
        started_at=NOW-timedelta(minutes=5), completed_at=NOW-timedelta(minutes=4),
    )
    db.add(result); db.commit(); return run, result


def _client(factory):
    def override_db():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m24_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_PAPER_PROJECTION_ENABLED is False
    assert configured.CANONICAL_PARSER_PAPER_PROJECTION_MAX_ARTIFACTS == 100


def test_m24_projectable_artifact():
    result = M24._project_artifact(_artifact())
    assert result["status"] == "PROJECTABLE"
    assert result["action"] == "BUY"
    assert result["projection_payload"]["paper_execution"] is False


def test_m24_review_unknown_side():
    result = M24._project_artifact(_artifact(side="UNKNOWN"))
    assert result["status"] == "REVIEW"
    assert "PAPER_PROJECTION_SIDE_UNKNOWN" in result["reason_codes"]


def test_m24_reject_failed_quality():
    result = M24._project_artifact(_artifact(quality="FAIL"))
    assert result["status"] == "REJECTED"


def test_m24_preview_blocked_without_certification(db_factory, monkeypatch):
    with db_factory() as db:
        monkeypatch.setattr(M24, "resolve_shadow_reliability_certification", lambda *a, **k: {"resolved_status": "UNCERTIFIED"})
        preview = M24.preview_paper_projection(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "BLOCKED"
        assert preview["paper_execution_authorized"] is False


def test_m24_preview_passed_with_projectable_source(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db); _source(db, [_artifact()])
        monkeypatch.setattr(M24, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        preview = M24.preview_paper_projection(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "PASSED"
        assert preview["metrics"]["projectable_count"] == 1


def test_m24_preview_partial_for_review_source(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db); _source(db, [_artifact(), _artifact(side="UNKNOWN")])
        monkeypatch.setattr(M24, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        preview = M24.preview_paper_projection(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "PARTIAL"
        assert preview["metrics"]["review_count"] == 1
        assert preview["metrics"]["projectable_count"] == 1


def test_m24_preview_insufficient_without_sources(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db)
        monkeypatch.setattr(M24, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        preview = M24.preview_paper_projection(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "INSUFFICIENT_DATA"


def test_m24_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(M24.CanonicalParserPaperProjectionError) as error:
            M24.run_paper_projection(db, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_PAPER_PROJECTION_DISABLED"


def test_m24_persistence_and_idempotency(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db); _source(db, [_artifact()])
        monkeypatch.setattr(M24, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        preview = M24.preview_paper_projection(db, settings_object=_policy(), evaluated_at=NOW)
        first = M24.run_paper_projection(db, confirmation=preview["confirmation"], settings_object=_policy(), started_at=NOW)
        second = M24.run_paper_projection(db, confirmation=preview["confirmation"], settings_object=_policy(), started_at=NOW)
        assert first["projection_id"] == second["projection_id"]
        assert db.query(CanonicalParserPaperProjectionRun).count() == 1
        assert db.query(CanonicalParserPaperProjectionResult).count() == 1
        assert first["paper_execution_authorized"] is False


def test_m24_resolve_passed_and_drifted(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db); _source(db, [_artifact()])
        monkeypatch.setattr(M24, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        preview = M24.preview_paper_projection(db, settings_object=_policy(), evaluated_at=NOW)
        M24.run_paper_projection(db, confirmation=preview["confirmation"], settings_object=_policy(), started_at=NOW)
        assert M24.resolve_paper_projection(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "PASSED"
        _source(db, [_artifact(side="SELL")])
        assert M24.resolve_paper_projection(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "DRIFTED"


def test_m24_status_counts(db_factory, monkeypatch):
    with db_factory() as db:
        cert = _certification(db); _source(db, [_artifact()])
        monkeypatch.setattr(M24, "resolve_shadow_reliability_certification", lambda *a, **k: _resolved(cert))
        preview = M24.preview_paper_projection(db, settings_object=_policy(), evaluated_at=NOW)
        M24.run_paper_projection(db, confirmation=preview["confirmation"], settings_object=_policy(), started_at=NOW)
        status = M24.get_paper_projection_status(db, settings_object=_policy())
        assert status["projection_run_count"] == 1
        assert status["projection_result_count"] == 1
        assert status["operational_guards"]["paper_order_writes"] is False


def test_m24_endpoint_requires_key_and_is_registered(db_factory):
    client = _client(db_factory)
    try:
        path = "/integrity/parser-paper-projection/status"
        assert client.get(path).status_code in {401, 403}
        response = client.get(path, headers={"X-Automation-Key": AUTOMATION_KEY})
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()


def test_m24_model_metadata_registered():
    assert "canonical_parser_paper_projection_runs" in Base.metadata.tables
    assert "canonical_parser_paper_projection_results" in Base.metadata.tables
