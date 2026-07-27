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
    CanonicalParserPaperProjectionReadinessEvidenceRun,
    CanonicalParserPaperProjectionResult,
    CanonicalParserPaperProjectionRun,
    CanonicalParserPaperRuntimeBinding,
)
from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_order import PaperOrder
from backend.app.models.paper_position import PaperPosition
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
import backend.app.services.blockchain_parser_paper_admission_canary_service as M28
import backend.app.services.blockchain_parser_paper_runtime_binding_service as M27

NOW = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)
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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_PAPER_ADMISSION_CANARY_ENABLED", False)


def _settings_values(**overrides):
    values = {"DATABASE_URL": "sqlite+pysqlite:///:memory:", "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com", "HELIUS_API_KEY": "test"}
    values.update(overrides)
    return values


def _policy(enabled=True, validity=15, fraction=0.5):
    return SimpleNamespace(
        CANONICAL_PARSER_PAPER_ADMISSION_CANARY_ENABLED=enabled,
        CANONICAL_PARSER_PAPER_ADMISSION_CANARY_VALIDITY_MINUTES=validity,
        CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_SOURCE_RUNS=3,
        CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_RESULTS=25,
        CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MIN_ADMISSIBLE_RESULTS=1,
        CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_CUMULATIVE_BUY_FRACTION=fraction,
    )


def _graph(db, *, action="BUY", sol_amount="0.1", token_amount="10", source_status="PROJECTABLE", cash=10.0, max_position=0.5, open_position=False):
    cert = CanonicalParserPaperAdmissionCertification(
        certification_id=str(uuid4()), certification_key=calculate_payload_hash({"m26": str(uuid4())}),
        assessment_db_id=77, assessment_id=str(uuid4()), assessment_key="1" * 64,
        reliability_certification_id=str(uuid4()), reliability_certification_event_hash="2" * 64,
        status="ACTIVE", evidence_hash="3" * 64, policy_version="m26", policy_hash="4" * 64,
        policy_snapshot={}, actor_label="TEST", note=None, certified_at=NOW-timedelta(minutes=5),
        expires_at=NOW+timedelta(minutes=60), revoked_at=None, revocation_reason=None,
        latest_event_sequence=1, latest_event_hash="5" * 64, technical_metadata={},
    )
    account = PaperAccount(
        name="M28 isolated", status="ACTIVE", starting_balance_sol=10.0, cash_balance_sol=cash,
        realized_pnl_sol=0.0, max_position_size_sol=max_position, max_open_positions=3, daily_loss_limit_sol=1.0,
    )
    db.add_all([cert, account]); db.flush()
    account_snapshot = M27._account_snapshot(account)
    binding = CanonicalParserPaperRuntimeBinding(
        binding_id=str(uuid4()), binding_key=calculate_payload_hash({"m27": str(uuid4())}),
        certification_db_id=cert.id, certification_id=cert.certification_id,
        certification_event_hash=cert.latest_event_hash, paper_account_id=account.id,
        paper_account_name=account.name, mode="READ_ONLY_CANARY", status="ACTIVE",
        account_snapshot_hash=calculate_payload_hash(account_snapshot), account_snapshot=account_snapshot,
        policy_version="m27", policy_hash="6" * 64, policy_snapshot={}, actor_label="TEST", note=None,
        bound_at=NOW-timedelta(minutes=2), expires_at=NOW+timedelta(minutes=60), unbound_at=None,
        unbind_reason=None, latest_event_sequence=1, latest_event_hash="7" * 64, technical_metadata={},
    )
    db.add(binding); db.flush()
    if open_position:
        db.add(PaperPosition(
            account_id=account.id, token_mint="T" * 44, status="OPEN", quantity=20.0,
            average_entry_price_sol=0.01, cost_basis_sol=0.2, last_price_sol=0.01,
            market_value_sol=0.2, unrealized_pnl_sol=0.0, realized_pnl_sol=0.0,
        ))
    run = CanonicalParserPaperProjectionRun(
        projection_id=str(uuid4()), projection_key=calculate_payload_hash({"m24": str(uuid4())}),
        certification_db_id=1, certification_id=str(uuid4()), certification_event_hash="8" * 64,
        assessment_id=str(uuid4()), source_run_count=1, source_result_count=1,
        projectable_count=1 if source_status == "PROJECTABLE" else 0,
        review_count=1 if source_status == "REVIEW" else 0,
        rejected_count=1 if source_status == "REJECTED" else 0,
        status="PASSED" if source_status == "PROJECTABLE" else "PARTIAL",
        policy_version="m24", policy_hash="9" * 64, policy_snapshot={},
        source_evidence_hash="a" * 64, source_snapshot={}, metrics_snapshot={}, reason_codes=[],
        actor_label="TEST", note=None, started_at=NOW-timedelta(minutes=4), completed_at=NOW-timedelta(minutes=3),
    )
    db.add(run); db.flush()
    result = CanonicalParserPaperProjectionResult(
        result_id=str(uuid4()), projection_run_db_id=run.id, sequence=1,
        source_execution_run_db_id=100, source_execution_run_id=str(uuid4()),
        source_result_db_id=101, source_result_id=str(uuid4()), raw_event_id=102, artifact_index=0,
        status=source_status, action=action, wallet_address="W" * 44, token_mint="T" * 44,
        token_amount=token_amount, sol_amount=sol_amount, artifact_hash="b" * 64,
        projection_hash=calculate_payload_hash({"projection": str(uuid4())}),
        projection_payload={"paper_execution": False}, reason_codes=[],
    )
    db.add(result); db.flush()
    db.add(CanonicalParserPaperProjectionReadinessEvidenceRun(
        assessment_db_id=cert.assessment_db_id, sequence=1, projection_run_db_id=run.id,
        projection_id=run.projection_id, status="PASSED", source_result_count=1,
        projectable_count=1 if source_status == "PROJECTABLE" else 0,
        review_count=1 if source_status == "REVIEW" else 0,
        rejected_count=1 if source_status == "REJECTED" else 0,
        projection_key=run.projection_key, policy_hash=run.policy_hash,
        source_evidence_hash=run.source_evidence_hash, run_evidence_hash="c" * 64,
        completed_at=run.completed_at,
    ))
    db.commit()
    return cert, account, binding, result


def _bound(binding, status="BOUND"):
    return {
        "resolved_status": status, "binding_id": binding.binding_id,
        "latest_event_hash": binding.latest_event_hash, "paper_runtime_bound": status == "BOUND",
        "paper_runtime_connected": False, "paper_execution_authorized": False, "live_execution_authorized": False,
    }


def _client(factory):
    def override_db():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _run(db, monkeypatch, **kwargs):
    _, account, binding, _ = _graph(db, **kwargs)
    monkeypatch.setattr(M28, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
    preview = M28.preview_paper_admission_canary(db, settings_object=_policy(), evaluated_at=NOW)
    result = M28.run_paper_admission_canary(db, confirmation=preview["confirmation"], settings_object=_policy(), evaluated_at=NOW)
    return account, binding, preview, result


def test_m28_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_PAPER_ADMISSION_CANARY_ENABLED is False
    assert configured.CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_RESULTS == 25
    assert configured.CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_CUMULATIVE_BUY_FRACTION == 0.5


def test_m28_preview_blocked_without_binding(db_factory, monkeypatch):
    with db_factory() as db:
        monkeypatch.setattr(M28, "resolve_paper_runtime_binding", lambda *a, **k: {"resolved_status": "UNBOUND"})
        preview = M28.preview_paper_admission_canary(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["eligible"] is False
        assert "PAPER_RUNTIME_BINDING_NOT_BOUND" in preview["reason_codes"]


def test_m28_buy_is_admissible_without_writes(db_factory, monkeypatch):
    with db_factory() as db:
        account, _, preview, result = _run(db, monkeypatch, action="BUY", sol_amount="0.1")
        assert preview["status"] == "PASSED"
        assert result["results"][0]["status"] == "ADMISSIBLE"
        db.refresh(account)
        assert account.cash_balance_sol == 10.0
        assert db.query(PaperOrder).count() == 0
        assert db.query(PaperPosition).count() == 0


def test_m28_buy_fraction_requires_review(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, binding, _ = _graph(db, action="BUY", sol_amount="0.4", cash=1.0, max_position=0.5)
        monkeypatch.setattr(M28, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M28.preview_paper_admission_canary(db, settings_object=_policy(fraction=0.25), evaluated_at=NOW)
        assert preview["status"] == "REVIEW"
        assert preview["results"][0]["status"] == "REVIEW"


def test_m28_buy_over_position_limit_is_blocked(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, binding, _ = _graph(db, action="BUY", sol_amount="0.6", max_position=0.5)
        monkeypatch.setattr(M28, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M28.preview_paper_admission_canary(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "BLOCKED"
        assert "MAX_POSITION_SIZE_EXCEEDED" in preview["results"][0]["reason_codes"]


def test_m28_sell_existing_position_is_admissible(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, binding, _ = _graph(db, action="SELL", token_amount="5", open_position=True)
        monkeypatch.setattr(M28, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M28.preview_paper_admission_canary(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "PASSED"
        assert preview["results"][0]["status"] == "ADMISSIBLE"


def test_m28_sell_missing_position_is_blocked(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, binding, _ = _graph(db, action="SELL", token_amount="5", open_position=False)
        monkeypatch.setattr(M28, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M28.preview_paper_admission_canary(db, settings_object=_policy(), evaluated_at=NOW)
        assert preview["status"] == "BLOCKED"
        assert "SELL_POSITION_MISSING" in preview["results"][0]["reason_codes"]


def test_m28_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(M28.CanonicalParserPaperAdmissionCanaryError) as error:
            M28.run_paper_admission_canary(db, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_PAPER_ADMISSION_CANARY_DISABLED"


def test_m28_persistence_and_idempotency(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, binding, _ = _graph(db)
        monkeypatch.setattr(M28, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        preview = M28.preview_paper_admission_canary(db, settings_object=_policy(), evaluated_at=NOW)
        first = M28.run_paper_admission_canary(db, confirmation=preview["confirmation"], settings_object=_policy(), evaluated_at=NOW)
        second = M28.run_paper_admission_canary(db, confirmation=preview["confirmation"], settings_object=_policy(), evaluated_at=NOW)
        assert first["canary_id"] == second["canary_id"]
        assert db.query(CanonicalParserPaperAdmissionCanaryRun).count() == 1
        assert db.query(CanonicalParserPaperAdmissionCanaryResult).count() == 1


def test_m28_resolve_passed_then_account_drifted(db_factory, monkeypatch):
    with db_factory() as db:
        account, binding, _, result = _run(db, monkeypatch)
        monkeypatch.setattr(M28, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        assert M28.resolve_paper_admission_canary(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "PASSED"
        account.cash_balance_sol = 9.0; db.commit()
        assert M28.resolve_paper_admission_canary(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "DRIFTED"


def test_m28_resolve_expired(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, binding, _ = _graph(db)
        monkeypatch.setattr(M28, "resolve_paper_runtime_binding", lambda *a, **k: _bound(binding))
        policy = _policy(validity=1)
        preview = M28.preview_paper_admission_canary(db, settings_object=policy, evaluated_at=NOW)
        M28.run_paper_admission_canary(db, confirmation=preview["confirmation"], settings_object=policy, evaluated_at=NOW)
        assert M28.resolve_paper_admission_canary(db, settings_object=policy, evaluated_at=NOW+timedelta(minutes=2))["resolved_status"] == "EXPIRED"


def test_m28_get_not_found(db_factory):
    with db_factory() as db:
        with pytest.raises(M28.CanonicalParserPaperAdmissionCanaryError) as error:
            M28.get_paper_admission_canary_run(db, str(uuid4()))
        assert error.value.status_code == 404


def test_m28_status_and_metadata(db_factory):
    with db_factory() as db:
        status = M28.get_paper_admission_canary_status(db, settings_object=_policy(False))
        assert status["run_count"] == 0
        assert status["operational_guards"]["paper_position_reads"] is True
        assert status["operational_guards"]["paper_position_writes"] is False
    assert "canonical_parser_paper_admission_canary_runs" in Base.metadata.tables
    assert "canonical_parser_paper_admission_canary_results" in Base.metadata.tables


def test_m28_endpoint_requires_key_and_is_registered(db_factory):
    client = _client(db_factory)
    try:
        path = "/integrity/parser-paper-admission-canary/status"
        assert client.get(path).status_code in {401, 403}
        response = client.get(path, headers={"X-Automation-Key": AUTOMATION_KEY})
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()
