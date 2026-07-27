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
    CanonicalParserPaperCanaryReadinessAssessment,
    CanonicalParserPaperExecutionPermit,
    CanonicalParserPaperExecutionPermitEvent,
    CanonicalParserPaperRuntimeBinding,
)
from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_order import PaperOrder
from backend.app.models.paper_position import PaperPosition
from backend.app.models.trade import Trade
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
import backend.app.services.blockchain_parser_paper_execution_permit_service as M30

NOW = datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc)
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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_ENABLED", False)


def _settings_values(**overrides):
    values = {
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "HELIUS_API_KEY": "test",
    }
    values.update(overrides)
    return values


def _policy(enabled=True, *, max_validity=60):
    return SimpleNamespace(
        CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_ENABLED=enabled,
        CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_VALIDITY_MINUTES=max_validity,
        CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_TOTAL_BUDGET_SOL=1.0,
        CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_ORDER_BUDGET_SOL=0.25,
        CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_ORDER_COUNT=20,
        CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MIN_READINESS_REMAINING_MINUTES=2,
    )


def _graph(db):
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
        name="M30 isolated",
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
    assessment = CanonicalParserPaperCanaryReadinessAssessment(
        assessment_id=str(uuid4()),
        assessment_key=calculate_payload_hash({"m29": str(uuid4())}),
        binding_db_id=binding.id,
        binding_id=binding.binding_id,
        binding_event_hash=binding.latest_event_hash,
        certification_id=binding.certification_id,
        paper_account_id=account.id,
        status="READY",
        run_count=3,
        passed_run_count=3,
        review_run_count=0,
        blocked_run_count=0,
        insufficient_run_count=0,
        result_count=3,
        admissible_count=3,
        review_result_count=0,
        blocked_result_count=0,
        observation_started_at=NOW - timedelta(minutes=10),
        observation_completed_at=NOW - timedelta(minutes=1),
        latest_source_valid_until=NOW + timedelta(minutes=10),
        freshness_cutoff_at=NOW - timedelta(minutes=30),
        policy_version="m29",
        policy_hash="9" * 64,
        policy_snapshot={},
        evidence_hash="a" * 64,
        evidence_snapshot={"canary_runs": []},
        metrics_snapshot={},
        reason_codes=[],
        actor_label="TEST",
        note=None,
        evaluated_at=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=30),
    )
    db.add(assessment)
    db.commit()
    return account, binding, assessment


def _ready(assessment):
    return {
        "resolved_status": "READY",
        "assessment_id": assessment.assessment_id,
        "evidence_hash": assessment.evidence_hash,
        "valid_until": assessment.valid_until,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


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


def _patch_sources(monkeypatch, assessment, binding):
    monkeypatch.setattr(M30, "resolve_paper_canary_readiness", lambda *a, **k: _ready(assessment))
    monkeypatch.setattr(M30, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))


def _client(factory):
    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _issue(db, monkeypatch, *, total=0.5, order=0.1, count=5, validity=15):
    account, binding, assessment = _graph(db)
    _patch_sources(monkeypatch, assessment, binding)
    preview = M30.preview_paper_execution_permit(
        db,
        readiness_assessment_id=assessment.assessment_id,
        validity_minutes=validity,
        total_budget_sol=total,
        max_order_budget_sol=order,
        max_order_count=count,
        settings_object=_policy(),
        evaluated_at=NOW,
    )
    result = M30.issue_paper_execution_permit(
        db,
        readiness_assessment_id=assessment.assessment_id,
        validity_minutes=validity,
        total_budget_sol=total,
        max_order_budget_sol=order,
        max_order_count=count,
        confirmation=preview["confirmation"],
        settings_object=_policy(),
        evaluated_at=NOW,
    )
    return account, binding, assessment, preview, result


def test_m30_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_ENABLED is False
    assert configured.CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_VALIDITY_MINUTES == 60
    assert configured.CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_TOTAL_BUDGET_SOL == 1.0


def test_m30_preview_ready_metadata_only(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, assessment = _graph(db)
        _patch_sources(monkeypatch, assessment, binding)
        preview = M30.preview_paper_execution_permit(
            db,
            readiness_assessment_id=assessment.assessment_id,
            total_budget_sol=0.5,
            max_order_budget_sol=0.1,
            max_order_count=5,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        assert preview["eligible"] is True
        assert preview["scope"] == "PAPER_EXECUTION_METADATA_ONLY"
        assert preview["budget_consumption_connected"] is False
        assert preview["paper_execution_authorized"] is False


def test_m30_preview_rejects_budget_above_policy(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, assessment = _graph(db)
        _patch_sources(monkeypatch, assessment, binding)
        preview = M30.preview_paper_execution_permit(
            db,
            total_budget_sol=2.0,
            max_order_budget_sol=0.1,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        assert preview["eligible"] is False
        assert "PAPER_EXECUTION_PERMIT_TOTAL_BUDGET_ABOVE_MAXIMUM" in preview["reason_codes"]


def test_m30_preview_cannot_outlive_readiness(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, assessment = _graph(db)
        assessment.valid_until = NOW + timedelta(minutes=10)
        db.commit()
        _patch_sources(monkeypatch, assessment, binding)
        preview = M30.preview_paper_execution_permit(
            db,
            validity_minutes=15,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        assert preview["eligible"] is False
        assert "PAPER_EXECUTION_PERMIT_EXCEEDS_READINESS_VALIDITY" in preview["reason_codes"]


def test_m30_preview_blocks_non_ready_assessment(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, assessment = _graph(db)
        monkeypatch.setattr(M30, "resolve_paper_canary_readiness", lambda *a, **k: {"resolved_status": "REVIEW", "assessment_id": assessment.assessment_id})
        monkeypatch.setattr(M30, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M30.preview_paper_execution_permit(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["eligible"] is False
        assert "PAPER_EXECUTION_PERMIT_READINESS_NOT_READY" in preview["reason_codes"]


def test_m30_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(M30.CanonicalParserPaperExecutionPermitError) as error:
            M30.issue_paper_execution_permit(db, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_DISABLED"


def test_m30_issue_persists_metadata_event_and_zero_consumption(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, _, _, result = _issue(db, monkeypatch)
        assert result["status"] == "ACTIVE"
        assert result["consumed_budget_sol"] == "0.000000000"
        assert result["consumed_order_count"] == 0
        assert result["remaining_budget_sol"] == "0.500000000"
        assert result["paper_execution_connected"] is False
        assert db.query(CanonicalParserPaperExecutionPermit).count() == 1
        assert db.query(CanonicalParserPaperExecutionPermitEvent).count() == 1
        assert db.query(PaperOrder).count() == 0
        assert db.query(PaperPosition).count() == 0
        assert db.query(Trade).count() == 0


def test_m30_issue_is_idempotent(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, assessment, preview, first = _issue(db, monkeypatch)
        second = M30.issue_paper_execution_permit(
            db,
            readiness_assessment_id=assessment.assessment_id,
            validity_minutes=15,
            total_budget_sol=0.5,
            max_order_budget_sol=0.1,
            max_order_count=5,
            confirmation=preview["confirmation"],
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        assert first["permit_id"] == second["permit_id"]
        assert db.query(CanonicalParserPaperExecutionPermit).count() == 1


def test_m30_different_active_permit_is_blocked(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, assessment, _, _ = _issue(db, monkeypatch)
        _patch_sources(monkeypatch, assessment, binding)
        preview = M30.preview_paper_execution_permit(
            db,
            readiness_assessment_id=assessment.assessment_id,
            total_budget_sol=0.4,
            max_order_budget_sol=0.1,
            max_order_count=4,
            settings_object=_policy(),
            evaluated_at=NOW,
        )
        assert preview["eligible"] is False
        assert "PAPER_EXECUTION_PERMIT_ACTIVE_PERMIT_EXISTS" in preview["reason_codes"]


def test_m30_revoke_appends_hash_chained_event(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, _, _, issued = _issue(db, monkeypatch)
        revoked = M30.revoke_paper_execution_permit(
            db,
            permit_id=issued["permit_id"],
            confirmation=f"REVOKE_PAPER_EXECUTION_PERMIT:{issued['permit_id']}",
            reason="manual governance stop",
            actor_label="TEST",
            revoked_at=NOW + timedelta(minutes=1),
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["latest_event_sequence"] == 2
        permit = db.query(CanonicalParserPaperExecutionPermit).one()
        assert M30._verify_event_chain(db, permit) == []
        assert db.query(CanonicalParserPaperExecutionPermitEvent).count() == 2


def test_m30_resolve_active_expired_and_drifted(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, assessment, _, issued = _issue(db, monkeypatch, validity=5)
        _patch_sources(monkeypatch, assessment, binding)
        assert M30.resolve_paper_execution_permit(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "ACTIVE"
        assert M30.resolve_paper_execution_permit(db, settings_object=_policy(), evaluated_at=NOW + timedelta(minutes=6))["resolved_status"] == "EXPIRED"
        monkeypatch.setattr(M30, "resolve_paper_canary_readiness", lambda *a, **k: {**_ready(assessment), "evidence_hash": "f" * 64})
        assert M30.resolve_paper_execution_permit(db, settings_object=_policy(), evaluated_at=NOW + timedelta(minutes=1))["resolved_status"] == "DRIFTED"


def test_m30_resolve_audit_invalid_on_event_tamper(db_factory, monkeypatch):
    with db_factory() as db:
        _, binding, assessment, _, _ = _issue(db, monkeypatch)
        _patch_sources(monkeypatch, assessment, binding)
        event = db.query(CanonicalParserPaperExecutionPermitEvent).one()
        event.event_hash = "0" * 64
        db.commit()
        resolved = M30.resolve_paper_execution_permit(db, settings_object=_policy(), evaluated_at=NOW)
        assert resolved["resolved_status"] == "AUDIT_INVALID"


def test_m30_status_metadata_and_openapi_registration(db_factory):
    with db_factory() as db:
        status = M30.get_paper_execution_permit_status(db, settings_object=_policy(False))
        assert status["permit_count"] == 0
        assert status["operational_guards"]["budget_consumption_connected"] is False
        assert status["operational_guards"]["paper_order_writes"] is False
    assert "canonical_parser_paper_execution_permits" in Base.metadata.tables
    assert "canonical_parser_paper_execution_permit_events" in Base.metadata.tables
    schema = app.openapi()
    assert "/integrity/parser-paper-execution-permit/issue" in schema["paths"]
    assert "/integrity/parser-paper-execution-permit/revoke" in schema["paths"]


def test_m30_endpoint_requires_automation_key(db_factory):
    client = _client(db_factory)
    try:
        path = "/integrity/parser-paper-execution-permit/status"
        assert client.get(path).status_code in {401, 403}
        response = client.get(path, headers={"X-Automation-Key": AUTOMATION_KEY})
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()
