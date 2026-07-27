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
    CanonicalParserPaperAdmissionCanaryResult,
    CanonicalParserPaperAdmissionCanaryRun,
    CanonicalParserPaperAdmissionCertification,
    CanonicalParserPaperCanaryReadinessAssessment,
    CanonicalParserPaperCanaryReadinessEvidenceRun,
    CanonicalParserPaperProjectionResult,
    CanonicalParserPaperProjectionRun,
    CanonicalParserPaperRuntimeBinding,
)
from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_order import PaperOrder
from backend.app.models.trade import Trade
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
import backend.app.services.blockchain_parser_paper_canary_readiness_service as M29

NOW = datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc)
AUTOMATION_KEY = "a" * 32


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def safe_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_API_KEY", AUTOMATION_KEY)
    monkeypatch.setattr(settings, "CANONICAL_PARSER_PAPER_CANARY_READINESS_ENABLED", False)


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test",
    }
    values.update(overrides)
    return values


def _policy(enabled=True, *, min_runs=3, min_admissible=None, max_age=30, validity=30):
    return SimpleNamespace(
        CANONICAL_PARSER_PAPER_CANARY_READINESS_ENABLED=enabled,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_LOOKBACK_MINUTES=1440,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_SOURCE_RUNS=20,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_RUNS=min_runs,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_RESULTS=min_runs,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_ADMISSIBLE_RESULTS=min_runs if min_admissible is None else min_admissible,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_REVIEW_RUNS=0,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_BLOCKED_RUNS=0,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_INSUFFICIENT_RUNS=0,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_OBSERVATION_MINUTES=5,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_SOURCE_AGE_MINUTES=max_age,
        CANONICAL_PARSER_PAPER_CANARY_READINESS_VALIDITY_MINUTES=validity,
    )


def _base_graph(db):
    certification = CanonicalParserPaperAdmissionCertification(
        certification_id=str(uuid4()),
        certification_key=calculate_payload_hash({"m26": str(uuid4())}),
        assessment_db_id=77,
        assessment_id=str(uuid4()),
        assessment_key="1" * 64,
        reliability_certification_id=str(uuid4()),
        reliability_certification_event_hash="2" * 64,
        status="ACTIVE",
        evidence_hash="3" * 64,
        policy_version="m26",
        policy_hash="4" * 64,
        policy_snapshot={},
        actor_label="TEST",
        note=None,
        certified_at=NOW - timedelta(minutes=20),
        expires_at=NOW + timedelta(hours=1),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash="5" * 64,
        technical_metadata={},
    )
    account = PaperAccount(
        name="M29 isolated",
        status="ACTIVE",
        starting_balance_sol=10.0,
        cash_balance_sol=10.0,
        realized_pnl_sol=0.0,
        max_position_size_sol=0.5,
        max_open_positions=3,
        daily_loss_limit_sol=1.0,
    )
    db.add_all([certification, account])
    db.flush()
    binding = CanonicalParserPaperRuntimeBinding(
        binding_id=str(uuid4()),
        binding_key=calculate_payload_hash({"m27": str(uuid4())}),
        certification_db_id=certification.id,
        certification_id=certification.certification_id,
        certification_event_hash=certification.latest_event_hash,
        paper_account_id=account.id,
        paper_account_name=account.name,
        mode="READ_ONLY_CANARY",
        status="ACTIVE",
        account_snapshot_hash="6" * 64,
        account_snapshot={},
        policy_version="m27",
        policy_hash="7" * 64,
        policy_snapshot={},
        actor_label="TEST",
        note=None,
        bound_at=NOW - timedelta(minutes=30),
        expires_at=NOW + timedelta(hours=1),
        unbound_at=None,
        unbind_reason=None,
        latest_event_sequence=1,
        latest_event_hash="8" * 64,
        technical_metadata={},
    )
    db.add(binding)
    db.flush()
    return certification, account, binding


def _add_canary(db, binding, *, completed_at, status="PASSED", suffix="a"):
    result_status = {
        "PASSED": "ADMISSIBLE",
        "REVIEW": "REVIEW",
        "BLOCKED": "BLOCKED",
        "INSUFFICIENT_DATA": "ADMISSIBLE",
    }[status]
    projection = CanonicalParserPaperProjectionRun(
        projection_id=str(uuid4()),
        projection_key=calculate_payload_hash({"projection": str(uuid4())}),
        certification_db_id=1,
        certification_id=str(uuid4()),
        certification_event_hash="9" * 64,
        assessment_id=str(uuid4()),
        source_run_count=1,
        source_result_count=1,
        projectable_count=1,
        review_count=0,
        rejected_count=0,
        status="PASSED",
        policy_version="m24",
        policy_hash="a" * 64,
        policy_snapshot={},
        source_evidence_hash="b" * 64,
        source_snapshot={},
        metrics_snapshot={},
        reason_codes=[],
        actor_label="TEST",
        note=None,
        started_at=completed_at - timedelta(seconds=10),
        completed_at=completed_at - timedelta(seconds=5),
    )
    db.add(projection)
    db.flush()
    projection_result = CanonicalParserPaperProjectionResult(
        result_id=str(uuid4()),
        projection_run_db_id=projection.id,
        sequence=1,
        source_execution_run_db_id=100,
        source_execution_run_id=str(uuid4()),
        source_result_db_id=101,
        source_result_id=str(uuid4()),
        raw_event_id=102,
        artifact_index=0,
        status="PROJECTABLE",
        action="BUY",
        wallet_address="W" * 44,
        token_mint=(suffix.upper() * 44)[:44],
        token_amount="10",
        sol_amount="0.1",
        artifact_hash="c" * 64,
        projection_hash=calculate_payload_hash({"projection_result": str(uuid4())}),
        projection_payload={"paper_execution": False},
        reason_codes=[],
    )
    db.add(projection_result)
    db.flush()

    counts = {
        "admissible": 1 if result_status == "ADMISSIBLE" else 0,
        "review": 1 if result_status == "REVIEW" else 0,
        "blocked": 1 if result_status == "BLOCKED" else 0,
    }
    account_hash = "d" * 64
    canary_policy = {
        "min_admissible_results": 2 if status == "INSUFFICIENT_DATA" else 1,
        "paper_execution_authorized": False,
    }
    policy_hash = calculate_payload_hash(canary_policy)
    source_hash = calculate_payload_hash({"source": suffix})
    canary_manifest = {
        "binding_id": binding.binding_id,
        "binding_event_hash": binding.latest_event_hash,
        "certification_id": binding.certification_id,
        "assessment_id": str(uuid4()),
        "paper_account_id": binding.paper_account_id,
        "source_evidence_hash": source_hash,
        "account_state_hash": account_hash,
        "policy_hash": policy_hash,
    }
    run = CanonicalParserPaperAdmissionCanaryRun(
        canary_id=str(uuid4()),
        canary_key=calculate_payload_hash(canary_manifest),
        binding_db_id=binding.id,
        binding_id=binding.binding_id,
        binding_event_hash=binding.latest_event_hash,
        certification_id=binding.certification_id,
        assessment_id=canary_manifest["assessment_id"],
        paper_account_id=binding.paper_account_id,
        source_result_count=1,
        admissible_count=counts["admissible"],
        review_count=counts["review"],
        blocked_count=counts["blocked"],
        status=status,
        source_evidence_hash=source_hash,
        account_state_hash=account_hash,
        account_state_snapshot={},
        policy_version="m28",
        policy_hash=policy_hash,
        policy_snapshot=canary_policy,
        metrics_snapshot={},
        reason_codes=[],
        actor_label="TEST",
        note=None,
        started_at=completed_at - timedelta(seconds=2),
        completed_at=completed_at,
        valid_until=NOW + timedelta(minutes=10),
    )
    db.add(run)
    db.flush()
    payload = {
        "sequence": 1,
        "source_result_id": projection_result.result_id,
        "source_projection_hash": projection_result.projection_hash,
        "status": result_status,
        "action": "BUY",
        "token_mint": projection_result.token_mint,
        "token_amount": "10",
        "sol_amount": "0.1",
        "projected_cash_after_sol": "9.9",
        "projected_open_positions": 1,
        "reason_codes": [],
        "paper_execution": False,
    }
    db.add(
        CanonicalParserPaperAdmissionCanaryResult(
            result_id=str(uuid4()),
            canary_run_db_id=run.id,
            sequence=1,
            source_projection_result_db_id=projection_result.id,
            source_projection_result_id=projection_result.result_id,
            source_projection_hash=projection_result.projection_hash,
            status=result_status,
            action="BUY",
            token_mint=projection_result.token_mint,
            token_amount="10",
            sol_amount="0.1",
            projected_cash_after_sol="9.9",
            projected_open_positions=1,
            canary_payload=payload,
            reason_codes=[],
            canary_hash=calculate_payload_hash(payload),
        )
    )
    db.flush()
    return run


def _ready_graph(db, *, statuses=("PASSED", "PASSED", "PASSED"), times=None):
    _, account, binding = _base_graph(db)
    times = times or [NOW - timedelta(minutes=10), NOW - timedelta(minutes=5), NOW - timedelta(minutes=1)]
    runs = [
        _add_canary(db, binding, completed_at=when, status=status, suffix=chr(97 + index))
        for index, (when, status) in enumerate(zip(times, statuses))
    ]
    db.commit()
    return account, binding, runs


def _bound(binding):
    return {
        "resolved_status": "BOUND",
        "binding_id": binding.binding_id,
        "latest_event_hash": binding.latest_event_hash,
        "paper_runtime_bound": True,
        "paper_runtime_connected": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _client(factory):
    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_m29_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_PAPER_CANARY_READINESS_ENABLED is False
    assert configured.CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_RUNS == 3
    assert configured.CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_SOURCE_AGE_MINUTES == 30


def test_m29_preview_ready_with_multiple_audited_runs_and_links(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, _ = _ready_graph(db)
        monkeypatch.setattr(M29, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M29.preview_paper_canary_readiness(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "READY"
        assert preview["metrics"]["run_count"] == 3
        assert preview["metrics"]["admissible_count"] == 3
        assert all(item["resource_link"].endswith(item["canary_id"]) for item in preview["evidence_snapshot"]["canary_runs"])
        assert preview["paper_execution_authorized"] is False


def test_m29_insufficient_when_minimum_runs_not_met(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, _ = _ready_graph(db, statuses=("PASSED", "PASSED"), times=[NOW - timedelta(minutes=6), NOW - timedelta(minutes=1)])
        monkeypatch.setattr(M29, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M29.preview_paper_canary_readiness(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "INSUFFICIENT_DATA"
        assert "PAPER_CANARY_READINESS_MIN_RUNS_NOT_MET" in preview["reason_codes"]


def test_m29_review_when_review_run_exceeds_policy(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, _ = _ready_graph(db, statuses=("PASSED", "REVIEW", "PASSED"))
        monkeypatch.setattr(M29, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M29.preview_paper_canary_readiness(db, settings_object=_policy(min_admissible=2), evaluated_at=NOW)
        assert preview["status"] == "REVIEW"
        assert "PAPER_CANARY_READINESS_REVIEW_RUN_LIMIT_EXCEEDED" in preview["reason_codes"]


def test_m29_blocks_tampered_m28_result_hash(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, _ = _ready_graph(db)
        item = db.query(CanonicalParserPaperAdmissionCanaryResult).first()
        item.canary_hash = "0" * 64
        db.commit()
        monkeypatch.setattr(M29, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M29.preview_paper_canary_readiness(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "BLOCKED"
        assert "PAPER_CANARY_READINESS_RESULT_HASH_INVALID" in preview["reason_codes"]


def test_m29_blocks_stale_evidence(db_factory, monkeypatch):
    with db_factory() as db:
        old = [NOW - timedelta(minutes=80), NOW - timedelta(minutes=70), NOW - timedelta(minutes=60)]
        _, binding, _ = _ready_graph(db, times=old)
        monkeypatch.setattr(M29, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M29.preview_paper_canary_readiness(db, settings_object=_policy(max_age=30), evaluated_at=NOW)
        assert preview["status"] == "BLOCKED"
        assert "PAPER_CANARY_READINESS_EVIDENCE_STALE" in preview["reason_codes"]


def test_m29_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(M29.CanonicalParserPaperCanaryReadinessError) as error:
            M29.execute_paper_canary_readiness_assessment(db, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_PAPER_CANARY_READINESS_DISABLED"


def test_m29_persistence_idempotency_and_no_execution_writes(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, _ = _ready_graph(db)
        monkeypatch.setattr(M29, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M29.preview_paper_canary_readiness(db, settings_object=_policy(), evaluated_at=NOW)
        first = M29.execute_paper_canary_readiness_assessment(
            db, confirmation=preview["confirmation"], settings_object=_policy(), evaluated_at=NOW
        )
        second = M29.execute_paper_canary_readiness_assessment(
            db, confirmation=preview["confirmation"], settings_object=_policy(), evaluated_at=NOW
        )
        assert first["assessment_id"] == second["assessment_id"]
        assert db.query(CanonicalParserPaperCanaryReadinessAssessment).count() == 1
        assert db.query(CanonicalParserPaperCanaryReadinessEvidenceRun).count() == 3
        assert db.query(PaperOrder).count() == 0
        assert db.query(Trade).count() == 0


def test_m29_resolve_ready_then_new_evidence_drifted(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, _ = _ready_graph(db)
        monkeypatch.setattr(M29, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M29.preview_paper_canary_readiness(db, settings_object=_policy(), evaluated_at=NOW)
        M29.execute_paper_canary_readiness_assessment(
            db, confirmation=preview["confirmation"], settings_object=_policy(), evaluated_at=NOW
        )
        assert M29.resolve_paper_canary_readiness(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "READY"
        _add_canary(db, binding, completed_at=NOW, status="PASSED", suffix="z")
        db.commit()
        assert M29.resolve_paper_canary_readiness(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "DRIFTED"


def test_m29_resolve_expired(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, _ = _ready_graph(db)
        monkeypatch.setattr(M29, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        policy = _policy(validity=1)
        preview = M29.preview_paper_canary_readiness(db, settings_object=policy, evaluated_at=NOW)
        M29.execute_paper_canary_readiness_assessment(
            db, confirmation=preview["confirmation"], settings_object=policy, evaluated_at=NOW
        )
        resolved = M29.resolve_paper_canary_readiness(db, settings_object=policy, evaluated_at=NOW + timedelta(minutes=2))
        assert resolved["resolved_status"] == "EXPIRED"


def test_m29_status_metadata_and_endpoint_openapi_registration(db_factory):
    with db_factory() as db:
        status = M29.get_paper_canary_readiness_status(db, settings_object=_policy(False))
        assert status["assessment_count"] == 0
        assert status["operational_guards"]["worker_connected"] is False
        assert status["operational_guards"]["paper_order_writes"] is False
    assert "canonical_parser_paper_canary_readiness_assessments" in Base.metadata.tables
    assert "canonical_parser_paper_canary_readiness_evidence_runs" in Base.metadata.tables
    schema = app.openapi()
    assert "/integrity/parser-paper-canary-readiness/assess" in schema["paths"]
    assert "/integrity/parser-paper-canary-readiness/resolve" in schema["paths"]


def test_m29_endpoint_requires_automation_key(db_factory):
    client = _client(db_factory)
    try:
        path = "/integrity/parser-paper-canary-readiness/status"
        assert client.get(path).status_code in {401, 403}
        response = client.get(path, headers={"X-Automation-Key": AUTOMATION_KEY})
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()
