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
    CanonicalParserPaperRuntimeBinding,
    CanonicalParserPaperRuntimeBindingEvent,
)
from backend.app.models.paper_account import PaperAccount
from backend.app.services.blockchain_integrity_service import calculate_payload_hash
import backend.app.services.blockchain_parser_paper_runtime_binding_service as M27

NOW = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
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
    monkeypatch.setattr(settings, "CANONICAL_PARSER_PAPER_RUNTIME_BINDING_ENABLED", False)


def _settings_values(**overrides):
    values = {"DATABASE_URL": "sqlite+pysqlite:///:memory:", "SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com", "HELIUS_API_KEY": "test"}
    values.update(overrides)
    return values


def _policy(enabled=True, validity=60):
    return SimpleNamespace(
        CANONICAL_PARSER_PAPER_RUNTIME_BINDING_ENABLED=enabled,
        CANONICAL_PARSER_PAPER_RUNTIME_BINDING_VALIDITY_MINUTES=validity,
    )


def _sources(db):
    cert = CanonicalParserPaperAdmissionCertification(
        certification_id=str(uuid4()), certification_key=calculate_payload_hash({"m26": str(uuid4())}),
        assessment_db_id=1, assessment_id=str(uuid4()), assessment_key="1" * 64,
        reliability_certification_id=str(uuid4()), reliability_certification_event_hash="2" * 64,
        status="ACTIVE", evidence_hash="3" * 64, policy_version="m26", policy_hash="4" * 64,
        policy_snapshot={}, actor_label="TEST", note=None, certified_at=NOW-timedelta(minutes=5),
        expires_at=NOW+timedelta(minutes=60), revoked_at=None, revocation_reason=None,
        latest_event_sequence=1, latest_event_hash="5" * 64, technical_metadata={},
    )
    account = PaperAccount(
        name="M27 isolated", status="ACTIVE", starting_balance_sol=10.0, cash_balance_sol=10.0,
        realized_pnl_sol=0.0, max_position_size_sol=0.5, max_open_positions=3, daily_loss_limit_sol=1.0,
    )
    db.add_all([cert, account]); db.commit()
    return cert, account


def _resolved(cert, status="CERTIFIED"):
    return {
        "resolved_status": status, "certification_id": cert.certification_id,
        "latest_event_hash": cert.latest_event_hash, "paper_admission_certified": status == "CERTIFIED",
        "paper_runtime_connected": False, "paper_execution_authorized": False, "live_execution_authorized": False,
    }


def _client(factory):
    def override_db():
        db = factory()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _bind(db, monkeypatch, policy=None):
    cert, account = _sources(db)
    monkeypatch.setattr(M27, "resolve_paper_admission_certification", lambda *a, **k: _resolved(cert))
    policy = policy or _policy()
    preview = M27.preview_paper_runtime_binding(db, paper_account_id=account.id, settings_object=policy, evaluated_at=NOW)
    result = M27.bind_paper_runtime(db, paper_account_id=account.id, confirmation=preview["confirmation"], settings_object=policy, bound_at=NOW)
    return cert, account, result


def test_m27_settings_defaults_fail_closed():
    configured = Settings(**_settings_values())
    assert configured.CANONICAL_PARSER_PAPER_RUNTIME_BINDING_ENABLED is False
    assert configured.CANONICAL_PARSER_PAPER_RUNTIME_BINDING_VALIDITY_MINUTES == 60


def test_m27_preview_blocked_without_certification_or_account(db_factory, monkeypatch):
    with db_factory() as db:
        monkeypatch.setattr(M27, "resolve_paper_admission_certification", lambda *a, **k: {"resolved_status": "UNCERTIFIED"})
        preview = M27.preview_paper_runtime_binding(db, paper_account_id=999, settings_object=_policy(), evaluated_at=NOW)
        assert preview["eligible"] is False
        assert "PAPER_ACCOUNT_NOT_FOUND" in preview["reason_codes"]


def test_m27_preview_eligible_for_active_account(db_factory, monkeypatch):
    with db_factory() as db:
        cert, account = _sources(db)
        monkeypatch.setattr(M27, "resolve_paper_admission_certification", lambda *a, **k: _resolved(cert))
        preview = M27.preview_paper_runtime_binding(db, paper_account_id=account.id, settings_object=_policy(), evaluated_at=NOW)
        assert preview["eligible"] is True
        assert preview["paper_account"]["status"] == "ACTIVE"
        assert preview["paper_execution_authorized"] is False


def test_m27_disabled_by_default(db_factory):
    with db_factory() as db:
        with pytest.raises(M27.CanonicalParserPaperRuntimeBindingError) as error:
            M27.bind_paper_runtime(db, paper_account_id=1, confirmation="x")
        assert error.value.code == "CANONICAL_PARSER_PAPER_RUNTIME_BINDING_DISABLED"


def test_m27_persistence_and_idempotency(db_factory, monkeypatch):
    with db_factory() as db:
        cert, account = _sources(db)
        monkeypatch.setattr(M27, "resolve_paper_admission_certification", lambda *a, **k: _resolved(cert))
        preview = M27.preview_paper_runtime_binding(db, paper_account_id=account.id, settings_object=_policy(), evaluated_at=NOW)
        first = M27.bind_paper_runtime(db, paper_account_id=account.id, confirmation=preview["confirmation"], settings_object=_policy(), bound_at=NOW)
        second = M27.bind_paper_runtime(db, paper_account_id=account.id, confirmation=preview["confirmation"], settings_object=_policy(), bound_at=NOW)
        assert first["binding_id"] == second["binding_id"]
        assert db.query(CanonicalParserPaperRuntimeBinding).count() == 1
        assert db.query(CanonicalParserPaperRuntimeBindingEvent).count() == 1


def test_m27_resolve_bound(db_factory, monkeypatch):
    with db_factory() as db:
        cert, _, result = _bind(db, monkeypatch)
        monkeypatch.setattr(M27, "resolve_paper_admission_certification", lambda *a, **k: _resolved(cert))
        resolved = M27.resolve_paper_runtime_binding(db, settings_object=_policy(), evaluated_at=NOW)
        assert resolved["resolved_status"] == "BOUND"
        assert resolved["binding_id"] == result["binding_id"]
        assert resolved["paper_runtime_connected"] is False


def test_m27_account_policy_drift_is_detected(db_factory, monkeypatch):
    with db_factory() as db:
        cert, account, _ = _bind(db, monkeypatch)
        account.max_position_size_sol = 0.75; db.commit()
        monkeypatch.setattr(M27, "resolve_paper_admission_certification", lambda *a, **k: _resolved(cert))
        assert M27.resolve_paper_runtime_binding(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "DRIFTED"


def test_m27_expired_binding_is_fail_closed(db_factory, monkeypatch):
    with db_factory() as db:
        cert, _, _ = _bind(db, monkeypatch, policy=_policy(validity=1))
        monkeypatch.setattr(M27, "resolve_paper_admission_certification", lambda *a, **k: _resolved(cert))
        assert M27.resolve_paper_runtime_binding(db, settings_object=_policy(validity=1), evaluated_at=NOW+timedelta(minutes=2))["resolved_status"] == "EXPIRED"


def test_m27_unbind_is_audited_and_idempotent(db_factory, monkeypatch):
    with db_factory() as db:
        _, _, result = _bind(db, monkeypatch)
        confirmation = f"{M27.PAPER_RUNTIME_UNBIND_PREFIX}:{result['binding_id']}"
        first = M27.unbind_paper_runtime(db, binding_id=result["binding_id"], confirmation=confirmation, reason="operator stop", unbound_at=NOW)
        second = M27.unbind_paper_runtime(db, binding_id=result["binding_id"], confirmation=confirmation, reason="operator stop", unbound_at=NOW)
        assert first["status"] == second["status"] == "UNBOUND"
        assert db.query(CanonicalParserPaperRuntimeBindingEvent).count() == 2


def test_m27_audit_tamper_is_detected(db_factory, monkeypatch):
    with db_factory() as db:
        cert, _, _ = _bind(db, monkeypatch)
        event = db.query(CanonicalParserPaperRuntimeBindingEvent).one()
        event.event_hash = "0" * 64; db.commit()
        monkeypatch.setattr(M27, "resolve_paper_admission_certification", lambda *a, **k: _resolved(cert))
        assert M27.resolve_paper_runtime_binding(db, settings_object=_policy(), evaluated_at=NOW)["resolved_status"] == "AUDIT_INVALID"


def test_m27_status_and_metadata(db_factory):
    with db_factory() as db:
        status = M27.get_paper_runtime_binding_status(db, settings_object=_policy(False))
        assert status["binding_count"] == 0
        assert status["operational_guards"]["paper_account_reads"] is True
        assert status["operational_guards"]["paper_account_writes"] is False
    assert "canonical_parser_paper_runtime_bindings" in Base.metadata.tables
    assert "canonical_parser_paper_runtime_binding_events" in Base.metadata.tables


def test_m27_endpoint_requires_key_and_is_registered(db_factory):
    client = _client(db_factory)
    try:
        path = "/integrity/parser-paper-runtime-binding/status"
        assert client.get(path).status_code in {401, 403}
        response = client.get(path, headers={"X-Automation-Key": AUTOMATION_KEY})
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    finally:
        app.dependency_overrides.clear()
