from __future__ import annotations

import ast
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
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
    CanonicalParserControlledLiveSubmission,
    CanonicalParserControlledLiveSubmissionEvent,
    CanonicalParserExternalSigningApproval,
    CanonicalParserMicroLiveCanaryPermit,
)
from backend.app.services.solana_rpc import SolanaRpcClient
import backend.app.services.blockchain_parser_controlled_live_submission_service as service
import backend.app.services.blockchain_parser_external_signing_approval_service as m37
from tests.test_parser_external_signing_approval_m37 import approve_ready
from tests.test_parser_live_transaction_dry_run_m36 import NOW


def settings_for_m38(**overrides):
    values = {
        "CANONICAL_PARSER_CONTROLLED_LIVE_SUBMISSION_ENABLED": True,
        "CANONICAL_PARSER_CONTROLLED_LIVE_SEND_RPC_ENABLED": True,
        "CANONICAL_PARSER_CONTROLLED_LIVE_RECONCILIATION_ENABLED": True,
        "CANONICAL_PARSER_CONTROLLED_LIVE_MAX_PENDING_SECONDS": 180,
        "RUN_LIVE_STREAM_WORKER": False,
        "RUN_LIVE_POSITION_MONITOR": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class SubmitRpc:
    def __init__(self, signature):
        self.signature = signature
        self.calls = 0

    def send_signed_transaction_base64(self, transaction):
        self.calls += 1
        return self.signature


class UncertainSubmitRpc:
    def send_signed_transaction_base64(self, transaction):
        raise RuntimeError("network outcome unknown")


class StatusRpc:
    def __init__(self, status):
        self.status = status

    def get_signature_status(self, signature):
        return dict(self.status)


class UnavailableStatusRpc:
    def get_signature_status(self, signature):
        raise RuntimeError("rpc unavailable")


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


def ready_context(db: Session, monkeypatch, *, token="m37-for-m38-001"):
    _, signed, approval = approve_ready(db, monkeypatch, token=token)
    row = db.scalar(
        select(CanonicalParserExternalSigningApproval).where(
            CanonicalParserExternalSigningApproval.approval_id
            == approval["approval_id"]
        )
    )
    return signed, row


def preview_ready(db: Session, monkeypatch, *, submission_token="m38-idempotency-001"):
    signed, approval = ready_context(db, monkeypatch)
    preview = service.preview_controlled_live_submission(
        db,
        approval_id=approval.approval_id,
        signed_transaction_base64=signed,
        idempotency_token=submission_token,
        settings_object=settings_for_m38(),
        evaluated_at=NOW + timedelta(seconds=2),
    )
    return signed, approval, preview


def submit_ready(db: Session, monkeypatch, *, submission_token="m38-idempotency-001"):
    signed, approval, preview = preview_ready(
        db, monkeypatch, submission_token=submission_token
    )
    rpc = SubmitRpc(approval.expected_signature)
    result = service.submit_controlled_live_transaction(
        db,
        approval_id=approval.approval_id,
        signed_transaction_base64=signed,
        idempotency_token=submission_token,
        confirmation=preview["confirmation"],
        settings_object=settings_for_m38(),
        submitted_at=NOW + timedelta(seconds=2),
        rpc_client=rpc,
    )
    return signed, approval, result, rpc


def test_m38_flags_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_CONTROLLED_LIVE_SUBMISSION_ENABLED is False
    assert configured.CANONICAL_PARSER_CONTROLLED_LIVE_SEND_RPC_ENABLED is False
    assert configured.CANONICAL_PARSER_CONTROLLED_LIVE_RECONCILIATION_ENABLED is False


def test_m38_models_registered():
    assert "canonical_parser_controlled_live_submissions" in Base.metadata.tables
    assert "canonical_parser_controlled_live_submission_events" in Base.metadata.tables


def test_m38_migration_is_consecutive_and_is_head():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("a3d5e8f1b297")
    assert revision.down_revision == "f2c4d7e0a186"
    assert len(scripts.get_heads()) == 1


def test_rpc_send_uses_fail_closed_options():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": "5" * 88,
            },
        )

    client = SolanaRpcClient(
        rpc_url="https://rpc.test", transport=httpx.MockTransport(handler)
    )
    signature = client.send_signed_transaction_base64("dGVzdA==")
    assert signature == "5" * 88
    assert captured["method"] == "sendTransaction"
    options = captured["params"][1]
    assert options["skipPreflight"] is False
    assert options["preflightCommitment"] == "confirmed"
    assert options["maxRetries"] == 0


def test_preview_ready_and_budget_reserved_conservatively(db, monkeypatch):
    _, _, preview = preview_ready(db, monkeypatch)
    assert preview["status"] == "READY"
    assert preview["ready"] is True
    assert preview["reservation"]["budget_sol"] == "0.010000000"
    assert preview["safety"]["legacy_kill_switch_engaged"] is True


def test_submission_requires_enabled_flag(db, monkeypatch):
    signed, approval, preview = preview_ready(db, monkeypatch)
    with pytest.raises(service.CanonicalParserControlledLiveSubmissionError) as exc:
        service.submit_controlled_live_transaction(
            db,
            approval_id=approval.approval_id,
            signed_transaction_base64=signed,
            idempotency_token="m38-idempotency-001",
            confirmation=preview["confirmation"],
            settings_object=settings_for_m38(
                CANONICAL_PARSER_CONTROLLED_LIVE_SUBMISSION_ENABLED=False
            ),
            submitted_at=NOW + timedelta(seconds=2),
            rpc_client=SubmitRpc(approval.expected_signature),
        )
    assert exc.value.code == "M38_DISABLED"


def test_submission_requires_rpc_flag(db, monkeypatch):
    signed, approval, preview = preview_ready(db, monkeypatch)
    with pytest.raises(service.CanonicalParserControlledLiveSubmissionError) as exc:
        service.submit_controlled_live_transaction(
            db,
            approval_id=approval.approval_id,
            signed_transaction_base64=signed,
            idempotency_token="m38-idempotency-001",
            confirmation=preview["confirmation"],
            settings_object=settings_for_m38(
                CANONICAL_PARSER_CONTROLLED_LIVE_SEND_RPC_ENABLED=False
            ),
            submitted_at=NOW + timedelta(seconds=2),
            rpc_client=SubmitRpc(approval.expected_signature),
        )
    assert exc.value.code == "M38_SEND_RPC_DISABLED"


def test_submission_requires_confirmation(db, monkeypatch):
    signed, approval, _ = preview_ready(db, monkeypatch)
    with pytest.raises(service.CanonicalParserControlledLiveSubmissionError) as exc:
        service.submit_controlled_live_transaction(
            db,
            approval_id=approval.approval_id,
            signed_transaction_base64=signed,
            idempotency_token="m38-idempotency-001",
            confirmation="wrong",
            settings_object=settings_for_m38(),
            submitted_at=NOW + timedelta(seconds=2),
            rpc_client=SubmitRpc(approval.expected_signature),
        )
    assert exc.value.code == "M38_CONFIRMATION_REQUIRED"


def test_successful_submission_retains_only_hashes(db, monkeypatch):
    signed, _, result, rpc = submit_ready(db, monkeypatch)
    assert result["status"] == "SUBMITTED"
    assert result["send_attempted"] is True
    assert result["raw_signed_transaction_persisted"] is False
    assert rpc.calls == 1
    row = db.scalar(select(CanonicalParserControlledLiveSubmission))
    assert signed not in str(row.submission_snapshot)
    assert db.query(CanonicalParserControlledLiveSubmissionEvent).count() == 2


def test_submission_rpc_uncertainty_keeps_reservation(db, monkeypatch):
    signed, approval, preview = preview_ready(db, monkeypatch)
    result = service.submit_controlled_live_transaction(
        db,
        approval_id=approval.approval_id,
        signed_transaction_base64=signed,
        idempotency_token="m38-idempotency-001",
        confirmation=preview["confirmation"],
        settings_object=settings_for_m38(),
        submitted_at=NOW + timedelta(seconds=2),
        rpc_client=UncertainSubmitRpc(),
    )
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert result["reserved_budget_sol"] == "0.010000000"
    assert "RPC_SUBMISSION_OUTCOME_UNCERTAIN" in result["reason_codes"]


def test_rpc_signature_mismatch_requires_reconciliation(db, monkeypatch):
    signed, approval, preview = preview_ready(db, monkeypatch)
    result = service.submit_controlled_live_transaction(
        db,
        approval_id=approval.approval_id,
        signed_transaction_base64=signed,
        idempotency_token="m38-idempotency-001",
        confirmation=preview["confirmation"],
        settings_object=settings_for_m38(),
        submitted_at=NOW + timedelta(seconds=2),
        rpc_client=SubmitRpc("different-signature"),
    )
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert "RPC_SIGNATURE_MISMATCH" in result["reason_codes"]


def test_submission_is_idempotent_and_not_resent(db, monkeypatch):
    signed, approval, first, rpc = submit_ready(db, monkeypatch)
    second_rpc = SubmitRpc(approval.expected_signature)
    second = service.submit_controlled_live_transaction(
        db,
        approval_id=approval.approval_id,
        signed_transaction_base64=signed,
        idempotency_token="m38-idempotency-001",
        confirmation="ignored-on-duplicate",
        settings_object=settings_for_m38(),
        submitted_at=NOW + timedelta(seconds=3),
        rpc_client=second_rpc,
    )
    assert first["submission_id"] == second["submission_id"]
    assert rpc.calls == 1
    assert second_rpc.calls == 0
    assert db.query(CanonicalParserControlledLiveSubmission).count() == 1


def test_budget_limit_blocks_submission(db, monkeypatch):
    signed, approval = ready_context(db, monkeypatch, token="m37-for-m38-budget")
    permit = db.scalar(select(CanonicalParserMicroLiveCanaryPermit))
    permit.total_budget_sol = 0.005
    permit.max_order_budget_sol = 0.005
    db.commit()
    preview = service.preview_controlled_live_submission(
        db,
        approval_id=approval.approval_id,
        signed_transaction_base64=signed,
        idempotency_token="m38-idempotency-budget",
        settings_object=settings_for_m38(),
        evaluated_at=NOW + timedelta(seconds=4),
    )
    assert preview["status"] == "BLOCKED"
    assert "M35_ORDER_BUDGET_EXCEEDED" in preview["reason_codes"]
    assert "M35_TOTAL_BUDGET_EXCEEDED" in preview["reason_codes"]


def ready_context(db: Session, monkeypatch, *, token: str = "m37-for-m38-001"):
    _, signed, approval = approve_ready(db, monkeypatch, token=token)
    row = db.scalar(
        select(CanonicalParserExternalSigningApproval).where(
            CanonicalParserExternalSigningApproval.approval_id
            == approval["approval_id"]
        )
    )
    return signed, row


def test_reconcile_confirmed(db, monkeypatch):
    _, _, submitted, _ = submit_ready(db, monkeypatch)
    result = service.reconcile_controlled_live_submission(
        db,
        submission_id=submitted["submission_id"],
        confirmation=(
            f"{service.RECONCILE_PREFIX}:{submitted['submission_id']}:"
            f"{submitted['expected_signature']}"
        ),
        settings_object=settings_for_m38(),
        reconciled_at=NOW + timedelta(seconds=5),
        rpc_client=StatusRpc(
            {
                "found": True,
                "confirmation_status": "confirmed",
                "confirmations": 1,
                "error": None,
                "slot": 123,
            }
        ),
    )
    assert result["status"] == "CONFIRMED"
    assert result["confirmation_slot"] == 123


def test_reconcile_finalized(db, monkeypatch):
    _, _, submitted, _ = submit_ready(db, monkeypatch)
    result = service.reconcile_controlled_live_submission(
        db,
        submission_id=submitted["submission_id"],
        confirmation=f"{service.RECONCILE_PREFIX}:{submitted['submission_id']}:{submitted['expected_signature']}",
        settings_object=settings_for_m38(),
        reconciled_at=NOW + timedelta(seconds=5),
        rpc_client=StatusRpc(
            {
                "found": True,
                "confirmation_status": "finalized",
                "confirmations": None,
                "error": None,
                "slot": 124,
            }
        ),
    )
    assert result["status"] == "FINALIZED"
    assert result["finalized_at"] is not None


def test_reconcile_on_chain_failure(db, monkeypatch):
    _, _, submitted, _ = submit_ready(db, monkeypatch)
    result = service.reconcile_controlled_live_submission(
        db,
        submission_id=submitted["submission_id"],
        confirmation=f"{service.RECONCILE_PREFIX}:{submitted['submission_id']}:{submitted['expected_signature']}",
        settings_object=settings_for_m38(),
        reconciled_at=NOW + timedelta(seconds=5),
        rpc_client=StatusRpc(
            {
                "found": True,
                "confirmation_status": "confirmed",
                "confirmations": 1,
                "error": {"InstructionError": [0, "x"]},
                "slot": 125,
            }
        ),
    )
    assert result["status"] == "FAILED"
    assert "ON_CHAIN_TRANSACTION_FAILED" in result["reason_codes"]


def test_reconcile_not_found_remains_uncertain(db, monkeypatch):
    _, _, submitted, _ = submit_ready(db, monkeypatch)
    result = service.reconcile_controlled_live_submission(
        db,
        submission_id=submitted["submission_id"],
        confirmation=f"{service.RECONCILE_PREFIX}:{submitted['submission_id']}:{submitted['expected_signature']}",
        settings_object=settings_for_m38(),
        reconciled_at=NOW + timedelta(seconds=5),
        rpc_client=StatusRpc(
            {
                "found": False,
                "confirmation_status": None,
                "confirmations": None,
                "error": None,
                "slot": None,
            }
        ),
    )
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert "SIGNATURE_NOT_FOUND" in result["reason_codes"]


def test_reconcile_unavailable_is_fail_closed(db, monkeypatch):
    _, _, submitted, _ = submit_ready(db, monkeypatch)
    result = service.reconcile_controlled_live_submission(
        db,
        submission_id=submitted["submission_id"],
        confirmation=f"{service.RECONCILE_PREFIX}:{submitted['submission_id']}:{submitted['expected_signature']}",
        settings_object=settings_for_m38(),
        reconciled_at=NOW + timedelta(seconds=5),
        rpc_client=UnavailableStatusRpc(),
    )
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert "RPC_RECONCILIATION_UNAVAILABLE" in result["reason_codes"]


def test_reconciliation_requires_enabled_flag(db, monkeypatch):
    _, _, submitted, _ = submit_ready(db, monkeypatch)
    with pytest.raises(service.CanonicalParserControlledLiveSubmissionError) as exc:
        service.reconcile_controlled_live_submission(
            db,
            submission_id=submitted["submission_id"],
            confirmation=f"{service.RECONCILE_PREFIX}:{submitted['submission_id']}:{submitted['expected_signature']}",
            settings_object=settings_for_m38(
                CANONICAL_PARSER_CONTROLLED_LIVE_RECONCILIATION_ENABLED=False
            ),
            rpc_client=StatusRpc({}),
        )
    assert exc.value.code == "M38_RECONCILIATION_DISABLED"


def test_m38_service_does_not_import_legacy_signer_or_trade_models():
    path = Path(service.__file__)
    tree = ast.parse(path.read_text())
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "backend.app.services.solana_transaction_signer" not in imports
    assert "backend.app.services.live_copy_trading_engine" not in imports
    source = path.read_text()
    assert "LIVE_TRADING_PRIVATE_KEY" not in source
    assert "Trade(" not in source
    assert "LiveOrder(" not in source


def test_m38_openapi_routes_present():
    paths = app.openapi()["paths"]
    required = {
        "/integrity/parser-controlled-live-submission/status",
        "/integrity/parser-controlled-live-submission/preview",
        "/integrity/parser-controlled-live-submission/submit",
        "/integrity/parser-controlled-live-submission/reconcile",
        "/integrity/parser-controlled-live-submission/submissions/{submission_id}",
        "/integrity/parser-controlled-live-submission/resolve",
    }
    assert required.issubset(paths)


def test_m38_endpoint_requires_automation_key(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get(
            "/integrity/parser-controlled-live-submission/status"
        )
        assert response.status_code in {401, 403, 503}
    finally:
        app.dependency_overrides.clear()
