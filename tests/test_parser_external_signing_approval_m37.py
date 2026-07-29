from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401
from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserExternalSigningApproval,
    CanonicalParserExternalSigningApprovalEvent,
    CanonicalParserLiveTransactionDryRun,
)
import backend.app.services.blockchain_parser_external_signing_approval_service as service
import backend.app.services.blockchain_parser_live_transaction_dry_run_service as m36
from tests.test_parser_live_transaction_dry_run_m36 import (
    NOW,
    PROGRAM,
    TOKEN,
    WALLET,
    PassingRpc,
    issue_profile,
    make_transaction,
    run_kwargs,
    seed_context,
    settings_for_m36,
)


def settings_for_m37(**overrides):
    values = {
        "CANONICAL_PARSER_EXTERNAL_SIGNING_APPROVAL_ENABLED": True,
        "CANONICAL_PARSER_EXTERNAL_SIGNING_RPC_ENABLED": True,
        "CANONICAL_PARSER_EXTERNAL_SIGNING_APPROVAL_TTL_SECONDS": 60,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class SignedPassingRpc:
    def simulate_transaction_base64(self, transaction):
        return {"units_consumed": 222, "logs": ["signed-ok"]}


class SignedFailingRpc:
    def simulate_transaction_base64(self, transaction):
        raise RuntimeError("signed simulation failed")


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


def build_ready_dry_run(db: Session):
    _, _, _, simulation = seed_context(db)
    profile = issue_profile(db)
    kwargs = run_kwargs(profile["profile_id"], simulation.simulation_id)
    preview = m36.preview_live_transaction_dry_run(
        db, **kwargs, settings_object=settings_for_m36(), evaluated_at=NOW
    )
    result = m36.run_live_transaction_dry_run(
        db,
        **kwargs,
        run_rpc_simulation=True,
        confirmation=preview["confirmation"],
        settings_object=settings_for_m36(),
        prepared_at=NOW,
        rpc_client=PassingRpc(),
    )
    return db.scalar(
        select(CanonicalParserLiveTransactionDryRun).where(
            CanonicalParserLiveTransactionDryRun.dry_run_id == result["dry_run_id"]
        )
    )


def valid_preview(db: Session, monkeypatch, *, token="m37-idempotency-001"):
    dry_run = build_ready_dry_run(db)
    monkeypatch.setattr(service, "_verify_signature", lambda *args: True)
    signed = make_transaction(signed=True)
    preview = service.preview_external_signing_approval(
        db,
        dry_run_id=dry_run.dry_run_id,
        signed_transaction_base64=signed,
        idempotency_token=token,
        settings_object=settings_for_m37(),
        evaluated_at=NOW + timedelta(seconds=1),
    )
    return dry_run, signed, preview


def approve_ready(db: Session, monkeypatch, *, token="m37-idempotency-001"):
    dry_run, signed, preview = valid_preview(db, monkeypatch, token=token)
    result = service.approve_external_signed_transaction(
        db,
        dry_run_id=dry_run.dry_run_id,
        signed_transaction_base64=signed,
        idempotency_token=token,
        run_rpc_simulation=True,
        confirmation=preview["confirmation"],
        settings_object=settings_for_m37(),
        verified_at=NOW + timedelta(seconds=1),
        rpc_client=SignedPassingRpc(),
    )
    return dry_run, signed, result


def test_m37_flags_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_EXTERNAL_SIGNING_APPROVAL_ENABLED is False
    assert configured.CANONICAL_PARSER_EXTERNAL_SIGNING_RPC_ENABLED is False


def test_m37_models_registered():
    assert "canonical_parser_external_signing_approvals" in Base.metadata.tables
    assert "canonical_parser_external_signing_approval_events" in Base.metadata.tables


def test_m37_migration_is_consecutive():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    revision = ScriptDirectory.from_config(config).get_revision("f2c4d7e0a186")
    assert revision.down_revision == "e1b3c6d9f075"


def test_signed_transaction_preview_ready(db, monkeypatch):
    _, _, preview = valid_preview(db, monkeypatch)
    assert preview["status"] == "READY"
    assert preview["ready"] is True
    assert preview["verified_signers"] == [WALLET]
    assert preview["safety"]["private_key_loaded"] is False


def test_preview_rejects_message_drift(db, monkeypatch):
    dry_run = build_ready_dry_run(db)
    monkeypatch.setattr(service, "_verify_signature", lambda *args: True)
    altered = make_transaction(signed=True, token=m36._base58_encode(bytes([6]) * 32))
    preview = service.preview_external_signing_approval(
        db,
        dry_run_id=dry_run.dry_run_id,
        signed_transaction_base64=altered,
        idempotency_token="m37-drift-001",
        settings_object=settings_for_m37(),
        evaluated_at=NOW + timedelta(seconds=1),
    )
    assert preview["status"] == "BLOCKED"
    assert "SIGNED_MESSAGE_HASH_DRIFT" in preview["reason_codes"]


def test_preview_rejects_invalid_signature(db, monkeypatch):
    dry_run = build_ready_dry_run(db)
    monkeypatch.setattr(service, "_verify_signature", lambda *args: False)
    preview = service.preview_external_signing_approval(
        db,
        dry_run_id=dry_run.dry_run_id,
        signed_transaction_base64=make_transaction(signed=True),
        idempotency_token="m37-badsig-001",
        settings_object=settings_for_m37(),
        evaluated_at=NOW + timedelta(seconds=1),
    )
    assert preview["status"] == "BLOCKED"
    assert "SIGNATURE_VERIFICATION_FAILED" in preview["reason_codes"]


def test_approval_requires_enabled_flag(db, monkeypatch):
    dry_run, signed, preview = valid_preview(db, monkeypatch)
    with pytest.raises(service.CanonicalParserExternalSigningApprovalError) as exc:
        service.approve_external_signed_transaction(
            db,
            dry_run_id=dry_run.dry_run_id,
            signed_transaction_base64=signed,
            idempotency_token="m37-idempotency-001",
            run_rpc_simulation=True,
            confirmation=preview["confirmation"],
            settings_object=settings_for_m37(
                CANONICAL_PARSER_EXTERNAL_SIGNING_APPROVAL_ENABLED=False
            ),
            verified_at=NOW + timedelta(seconds=1),
            rpc_client=SignedPassingRpc(),
        )
    assert exc.value.code == "M37_DISABLED"


def test_approval_requires_confirmation(db, monkeypatch):
    dry_run, signed, _ = valid_preview(db, monkeypatch)
    with pytest.raises(service.CanonicalParserExternalSigningApprovalError) as exc:
        service.approve_external_signed_transaction(
            db,
            dry_run_id=dry_run.dry_run_id,
            signed_transaction_base64=signed,
            idempotency_token="m37-idempotency-001",
            run_rpc_simulation=True,
            confirmation="wrong",
            settings_object=settings_for_m37(),
            verified_at=NOW + timedelta(seconds=1),
            rpc_client=SignedPassingRpc(),
        )
    assert exc.value.code == "M37_CONFIRMATION_REQUIRED"


def test_approval_ready_and_does_not_persist_raw_transaction(db, monkeypatch):
    _, signed, result = approve_ready(db, monkeypatch)
    assert result["status"] == "READY"
    assert result["rpc_simulation_status"] == "PASSED"
    assert result["raw_signed_transaction_persisted"] is False
    row = db.scalar(select(CanonicalParserExternalSigningApproval))
    assert signed not in str(row.verification_snapshot)
    assert db.query(CanonicalParserExternalSigningApprovalEvent).count() == 1


def test_rpc_skipped_produces_review(db, monkeypatch):
    dry_run, signed, preview = valid_preview(db, monkeypatch, token="m37-skip-001")
    result = service.approve_external_signed_transaction(
        db,
        dry_run_id=dry_run.dry_run_id,
        signed_transaction_base64=signed,
        idempotency_token="m37-skip-001",
        run_rpc_simulation=False,
        confirmation=preview["confirmation"],
        settings_object=settings_for_m37(),
        verified_at=NOW + timedelta(seconds=1),
    )
    assert result["status"] == "REVIEW"
    assert "SIGNED_RPC_SIMULATION_SKIPPED" in result["reason_codes"]


def test_rpc_failure_blocks_approval(db, monkeypatch):
    dry_run, signed, preview = valid_preview(db, monkeypatch, token="m37-rpcfail-001")
    result = service.approve_external_signed_transaction(
        db,
        dry_run_id=dry_run.dry_run_id,
        signed_transaction_base64=signed,
        idempotency_token="m37-rpcfail-001",
        run_rpc_simulation=True,
        confirmation=preview["confirmation"],
        settings_object=settings_for_m37(),
        verified_at=NOW + timedelta(seconds=1),
        rpc_client=SignedFailingRpc(),
    )
    assert result["status"] == "BLOCKED"
    assert result["rpc_simulation_status"] == "FAILED"


def test_approval_is_idempotent(db, monkeypatch):
    dry_run, signed, first = approve_ready(db, monkeypatch)
    second = service.approve_external_signed_transaction(
        db,
        dry_run_id=dry_run.dry_run_id,
        signed_transaction_base64=signed,
        idempotency_token="m37-idempotency-001",
        run_rpc_simulation=True,
        confirmation="ignored-on-duplicate",
        settings_object=settings_for_m37(),
        verified_at=NOW + timedelta(seconds=2),
        rpc_client=SignedPassingRpc(),
    )
    assert first["approval_id"] == second["approval_id"]
    assert db.query(CanonicalParserExternalSigningApproval).count() == 1


def test_approval_can_be_revoked(db, monkeypatch):
    _, _, approved = approve_ready(db, monkeypatch)
    result = service.revoke_external_signing_approval(
        db,
        approval_id=approved["approval_id"],
        confirmation=(
            f"{service.REVOKE_PREFIX}:{approved['approval_id']}:"
            f"{approved['approval_envelope_hash']}"
        ),
        reason="operator stop",
        revoked_at=NOW + timedelta(seconds=2),
    )
    assert result["status"] == "REVOKED"
    assert db.query(CanonicalParserExternalSigningApprovalEvent).count() == 2


def test_m37_status_and_resolve(db, monkeypatch):
    assert service.resolve_external_signing_approval(db)["resolved_status"] == "EMPTY"
    approve_ready(db, monkeypatch)
    row = db.scalar(select(CanonicalParserExternalSigningApproval))
    row.expires_at = service._utc_now() + timedelta(hours=1)
    db.commit()
    assert service.get_external_signing_approval_status(
        db, settings_object=settings_for_m37()
    )["approval_count"] == 1
    assert service.resolve_external_signing_approval(db)["resolved_status"] == "READY"


def test_m37_service_has_no_signer_or_submission_calls():
    path = Path(service.__file__)
    tree = ast.parse(path.read_text())
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "backend.app.services.solana_transaction_signer" not in imports
    assert "sign_base64_versioned_transaction" not in calls
    assert "send_signed_transaction_base64" not in calls
    source = path.read_text()
    assert "LIVE_TRADING_PRIVATE_KEY" not in source


def test_m37_openapi_routes_present():
    paths = app.openapi()["paths"]
    required = {
        "/integrity/parser-external-signing-approval/status",
        "/integrity/parser-external-signing-approval/preview",
        "/integrity/parser-external-signing-approval/approve",
        "/integrity/parser-external-signing-approval/revoke",
        "/integrity/parser-external-signing-approval/approvals/{approval_id}",
        "/integrity/parser-external-signing-approval/resolve",
    }
    assert required.issubset(paths)


def test_m37_endpoint_requires_automation_key(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get(
            "/integrity/parser-external-signing-approval/status"
        )
        assert response.status_code in {401, 403, 503}
    finally:
        app.dependency_overrides.clear()
