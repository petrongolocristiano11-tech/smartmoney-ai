from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
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
    CanonicalParserPaperCalibrationCampaign,
    CanonicalParserPaperCampaignItem,
    CanonicalParserPaperCampaignRun,
    CanonicalParserPaperExecutionPermit,
    CanonicalParserPaperOperationalAssessment,
    CanonicalParserPermitBoundPaperExecution,
)
from backend.app.models.paper_account import PaperAccount
import backend.app.services.blockchain_parser_paper_campaign_orchestration_service as service

NOW = datetime(2026, 7, 28, 21, 0, tzinfo=timezone.utc)


def settings_for_m34(**overrides):
    values = {
        "CANONICAL_PARSER_PAPER_CAMPAIGN_ORCHESTRATION_ENABLED": True,
        "CANONICAL_PARSER_PAPER_CAMPAIGN_MAX_ITEMS": 10,
        "CANONICAL_PARSER_PAPER_CAMPAIGN_RECOVERY_LIMIT": 25,
        "CANONICAL_PARSER_PAPER_OPERATIONAL_LOOKBACK_HOURS": 24,
        "CANONICAL_PARSER_PAPER_OPERATIONAL_MIN_SETTLED": 2,
        "CANONICAL_PARSER_PAPER_OPERATIONAL_MAX_RECONCILIATION_REQUIRED": 0,
        "CANONICAL_PARSER_PAPER_OPERATIONAL_MIN_RELIABILITY_SCORE": 98.0,
        "CANONICAL_PARSER_PAPER_OPERATIONAL_MAX_CALIBRATION_GAP_PERCENT": 20.0,
        "CANONICAL_PARSER_PAPER_OPERATIONAL_MAX_CALIBRATION_AGE_MINUTES": 120,
        "CANONICAL_PARSER_PAPER_OPERATIONAL_VALIDITY_MINUTES": 30,
        "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_RESERVATION_TIMEOUT_MINUTES": 10,
        "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_ENABLED": True,
        "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_MAX_SLIPPAGE_PERCENT": 5.0,
        "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_MAX_FEE_PERCENT": 2.0,
        "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_MAX_DECISION_AGE_MINUTES": 30,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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


def item(decision="10000000-0000-0000-0000-000000000001", token="token-12345678"):
    return {
        "decision_result_id": decision,
        "side": "BUY",
        "market_price_sol": 0.001,
        "quantity": None,
        "slippage_percent": 0.5,
        "fee_percent": 0.25,
        "idempotency_token": token,
    }


def fake_preview(decision_id: str, *, execution=None):
    key = (decision_id.replace("-", "") + "0" * 64)[:64]
    return {
        "ready": execution is None,
        "existing_execution": execution,
        "paper_account_id": 1,
        "decision_result_id": decision_id,
        "side": "BUY",
        "token_mint": "TokenMint111111111111111111111111111111111111",
        "requested_budget_sol": "0.100000000",
        "idempotency_key": key,
        "confirmation": f"confirm-{decision_id}",
    }


def seed_account_permit(db: Session):
    account = PaperAccount(
        name="m34-account",
        status="ACTIVE",
        starting_balance_sol=10,
        cash_balance_sol=10,
        realized_pnl_sol=0,
        max_position_size_sol=1,
        max_open_positions=10,
        daily_loss_limit_sol=5,
    )
    db.add(account)
    db.flush()
    permit = CanonicalParserPaperExecutionPermit(
        permit_id="20000000-0000-0000-0000-000000000001",
        permit_key="2" * 64,
        readiness_assessment_db_id=1,
        readiness_assessment_id="21000000-0000-0000-0000-000000000001",
        readiness_evidence_hash="3" * 64,
        binding_db_id=1,
        binding_id="22000000-0000-0000-0000-000000000001",
        binding_event_hash="4" * 64,
        certification_id="23000000-0000-0000-0000-000000000001",
        paper_account_id=account.id,
        paper_account_name=account.name,
        scope="PAPER_EXECUTION_METADATA_ONLY",
        status="ACTIVE",
        requested_validity_minutes=60,
        total_budget_sol=1,
        max_order_budget_sol=0.2,
        max_order_count=10,
        consumed_budget_sol=0,
        consumed_order_count=0,
        policy_version="m30-test",
        policy_hash="5" * 64,
        policy_snapshot={},
        actor_label="TEST",
        note=None,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=2),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash="6" * 64,
        technical_metadata={},
    )
    db.add(permit)
    db.commit()
    return account, permit


def seed_settled(db: Session, account: PaperAccount, permit: CanonicalParserPaperExecutionPermit, sequence: int):
    row = CanonicalParserPermitBoundPaperExecution(
        execution_id=f"30000000-0000-0000-0000-{sequence:012d}",
        idempotency_key=(str(sequence) * 64)[:64],
        permit_db_id=permit.id,
        permit_id=permit.permit_id,
        decision_result_db_id=sequence,
        decision_result_id=f"31000000-0000-0000-0000-{sequence:012d}",
        decision_hash="7" * 64,
        paper_account_id=account.id,
        paper_order_id=None,
        paper_position_id=None,
        side="BUY",
        status="SETTLED",
        token_mint=f"TokenMint{sequence:044d}"[-52:],
        requested_budget_sol=0.1,
        reserved_budget_sol=0.1,
        settled_budget_sol=0.1,
        quantity=100,
        market_price_sol=0.001,
        slippage_percent=0.5,
        fee_percent=0.25,
        signal_score=80,
        confidence_score=80,
        permit_budget_before_sol=0,
        permit_order_count_before=0,
        reservation_hash="8" * 64,
        settlement_hash="9" * 64,
        failure_code=None,
        failure_message=None,
        actor_label="TEST",
        note=None,
        reserved_at=NOW - timedelta(minutes=5),
        settled_at=NOW - timedelta(minutes=4),
        released_at=None,
        technical_metadata={},
    )
    db.add(row)
    return row


def seed_calibration(db: Session, account: PaperAccount, *, status="READY", reliability=100, gap=5):
    row = CanonicalParserPaperCalibrationCampaign(
        campaign_id="40000000-0000-0000-0000-000000000001",
        campaign_key="a" * 64,
        scope="PAPER_ANALYTICS_ONLY",
        status=status,
        paper_account_id=account.id,
        permit_id=None,
        attempt_count=2,
        settled_count=2,
        released_count=0,
        failed_count=0,
        reconciliation_required_count=0,
        buy_count=2,
        sell_count=0,
        closed_outcome_count=2,
        winning_outcome_count=2,
        realized_pnl_sol=0.1,
        total_fee_sol=0.001,
        estimated_slippage_cost_sol=0.001,
        win_rate_percent=100,
        profit_factor=2,
        brier_score=0.1,
        calibration_gap_percent=gap,
        reliability_score=reliability,
        policy_version="m33-test",
        policy_hash="b" * 64,
        policy_snapshot={},
        summary={},
        segments={},
        recommendations=[],
        reason_codes=[],
        evidence_hash="c" * 64,
        actor_label="TEST",
        note=None,
        window_started_at=NOW - timedelta(hours=1),
        window_ended_at=NOW,
        completed_at=NOW - timedelta(minutes=5),
    )
    db.add(row)
    db.commit()
    return row


def test_m34_flag_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_PAPER_CAMPAIGN_ORCHESTRATION_ENABLED is False


def test_m34_models_registered():
    assert "canonical_parser_paper_campaign_runs" in Base.metadata.tables
    assert "canonical_parser_paper_campaign_items" in Base.metadata.tables
    assert "canonical_parser_paper_operational_assessments" in Base.metadata.tables


def test_m34_migration_consecutive():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    assert ScriptDirectory.from_config(config).get_revision("c9f1a4b7d853").down_revision == "b8e5d0f3a742"


def test_m34_service_has_no_live_execution_imports_or_automation_calls():
    path = Path("backend/app/services/blockchain_parser_paper_campaign_orchestration_service.py")
    tree = ast.parse(path.read_text())
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any("live_copy_trading" in name or "solana_transaction_signer" in name for name in imports)
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "start" not in calls and "execute_order" not in calls


def test_preview_rejects_duplicate_items(db, monkeypatch):
    monkeypatch.setattr(service, "preview_permit_bound_paper_execution", lambda *a, **k: fake_preview(k["decision_result_id"]))
    with pytest.raises(service.CanonicalParserPaperCampaignError) as exc:
        service.preview_paper_campaign(db, permit_id="2" * 36, items=[item(), item()], settings_object=settings_for_m34())
    assert exc.value.code == "PAPER_CAMPAIGN_DUPLICATE_ITEM"


def test_preview_builds_bounded_manual_campaign(db, monkeypatch):
    monkeypatch.setattr(service, "preview_permit_bound_paper_execution", lambda *a, **k: fake_preview(k["decision_result_id"]))
    payload = service.preview_paper_campaign(db, permit_id="2" * 36, items=[item()], settings_object=settings_for_m34())
    assert payload["ready"] is True
    assert payload["requested_count"] == 1
    assert payload["requested_budget_sol"] == "0.100000000"
    assert payload["safety"]["worker_connected"] is False


def test_run_requires_enabled_flag(db, monkeypatch):
    monkeypatch.setattr(service, "preview_permit_bound_paper_execution", lambda *a, **k: fake_preview(k["decision_result_id"]))
    with pytest.raises(service.CanonicalParserPaperCampaignError) as exc:
        service.run_paper_campaign(db, permit_id="2" * 36, items=[item()], confirmation="x", settings_object=settings_for_m34(CANONICAL_PARSER_PAPER_CAMPAIGN_ORCHESTRATION_ENABLED=False))
    assert exc.value.code == "PAPER_CAMPAIGN_DISABLED"


def test_run_persists_settled_campaign_and_items(db, monkeypatch):
    monkeypatch.setattr(service, "preview_permit_bound_paper_execution", lambda *a, **k: fake_preview(k["decision_result_id"]))
    monkeypatch.setattr(
        service,
        "execute_permit_bound_paper",
        lambda *a, **k: {
            "execution_id": "50000000-0000-0000-0000-000000000001",
            "status": "SETTLED",
            "decision_result_id": k["decision_result_id"],
            "side": k["side"],
            "token_mint": "TokenMint111111111111111111111111111111111111",
            "requested_budget_sol": "0.100000000",
            "settled_budget_sol": "0.100000000",
            "idempotency_key": "d" * 64,
            "failure_code": None,
        },
    )
    preview = service.preview_paper_campaign(db, permit_id="2" * 36, items=[item()], settings_object=settings_for_m34())
    result = service.run_paper_campaign(db, permit_id="2" * 36, items=[item()], confirmation=preview["confirmation"], settings_object=settings_for_m34(), executed_at=NOW)
    assert result["status"] == "COMPLETED"
    assert db.scalar(select(CanonicalParserPaperCampaignRun)).settled_count == 1
    assert db.scalar(select(CanonicalParserPaperCampaignItem)).status == "SETTLED"


def test_run_marks_reconciliation_required(db, monkeypatch):
    monkeypatch.setattr(service, "preview_permit_bound_paper_execution", lambda *a, **k: fake_preview(k["decision_result_id"]))
    monkeypatch.setattr(service, "execute_permit_bound_paper", lambda *a, **k: {
        "execution_id": "50000000-0000-0000-0000-000000000002", "status": "RECONCILIATION_REQUIRED",
        "decision_result_id": k["decision_result_id"], "side": k["side"],
        "token_mint": "TokenMint111111111111111111111111111111111111",
        "requested_budget_sol": "0.100000000", "settled_budget_sol": "0", "idempotency_key": "e" * 64,
        "failure_code": "ORDER_NOT_YET_VISIBLE",
    })
    preview = service.preview_paper_campaign(db, permit_id="2" * 36, items=[item()], settings_object=settings_for_m34())
    result = service.run_paper_campaign(db, permit_id="2" * 36, items=[item()], confirmation=preview["confirmation"], settings_object=settings_for_m34(), executed_at=NOW)
    assert result["status"] == "RECONCILIATION_REQUIRED"


def test_campaign_key_is_idempotent(db, monkeypatch):
    existing = {
        "execution_id": "50000000-0000-0000-0000-000000000003", "status": "SETTLED", "paper_account_id": 1,
        "decision_result_id": item()["decision_result_id"], "side": "BUY", "token_mint": "TokenMint111111111111111111111111111111111111",
        "requested_budget_sol": "0.1", "settled_budget_sol": "0.1", "idempotency_key": "f" * 64,
    }
    monkeypatch.setattr(service, "preview_permit_bound_paper_execution", lambda *a, **k: fake_preview(k["decision_result_id"], execution=existing))
    first = service.preview_paper_campaign(db, permit_id="2" * 36, items=[item()], settings_object=settings_for_m34())
    assert first["ready"] is True


def test_operational_preview_insufficient_without_calibration(db):
    account, _ = seed_account_permit(db)
    payload = service.preview_paper_operational_assessment(db, paper_account_id=account.id, settings_object=settings_for_m34(), evaluated_at=NOW)
    assert payload["status"] == "INSUFFICIENT_DATA"
    assert "CALIBRATION_CAMPAIGN_MISSING" in payload["reason_codes"]


def test_operational_preview_ready_with_reliable_clean_evidence(db):
    account, permit = seed_account_permit(db)
    seed_settled(db, account, permit, 1)
    seed_settled(db, account, permit, 2)
    permit.consumed_budget_sol = 0.2
    permit.consumed_order_count = 2
    db.commit()
    seed_calibration(db, account)
    payload = service.preview_paper_operational_assessment(db, paper_account_id=account.id, settings_object=settings_for_m34(), evaluated_at=NOW)
    assert payload["status"] == "READY"
    assert payload["budget_drift_count"] == 0


def test_operational_preview_blocks_budget_drift(db):
    account, permit = seed_account_permit(db)
    seed_settled(db, account, permit, 1)
    seed_settled(db, account, permit, 2)
    db.commit()
    seed_calibration(db, account)
    payload = service.preview_paper_operational_assessment(db, paper_account_id=account.id, settings_object=settings_for_m34(), evaluated_at=NOW)
    assert payload["status"] == "BLOCKED"
    assert "PERMIT_BUDGET_DRIFT" in payload["reason_codes"]


def test_operational_assessment_requires_confirmation_and_persists(db):
    account, permit = seed_account_permit(db)
    seed_settled(db, account, permit, 1)
    seed_settled(db, account, permit, 2)
    permit.consumed_budget_sol = 0.2
    permit.consumed_order_count = 2
    db.commit()
    seed_calibration(db, account)
    preview = service.preview_paper_operational_assessment(db, paper_account_id=account.id, settings_object=settings_for_m34(), evaluated_at=NOW)
    with pytest.raises(service.CanonicalParserPaperCampaignError):
        service.assess_paper_operations(db, paper_account_id=account.id, calibration_campaign_id=None, confirmation="wrong", settings_object=settings_for_m34(), evaluated_at=NOW)
    result = service.assess_paper_operations(db, paper_account_id=account.id, calibration_campaign_id=None, confirmation=preview["confirmation"], settings_object=settings_for_m34(), evaluated_at=NOW)
    assert result["status"] == "READY"
    assert db.scalar(select(CanonicalParserPaperOperationalAssessment)).evidence_hash == result["evidence_hash"]


def test_m34_openapi_operations_and_automation_header():
    schema = app.openapi()
    required = {
        ("get", "/integrity/parser-paper-campaign/status"),
        ("post", "/integrity/parser-paper-campaign/preview"),
        ("post", "/integrity/parser-paper-campaign/run"),
        ("post", "/integrity/parser-paper-campaign/recover"),
        ("get", "/integrity/parser-paper-campaign/campaigns/{campaign_id}"),
        ("get", "/integrity/parser-paper-campaign/operational-preview"),
        ("post", "/integrity/parser-paper-campaign/operational-assess"),
        ("get", "/integrity/parser-paper-campaign/assessments/{assessment_id}"),
        ("get", "/integrity/parser-paper-campaign/resolve"),
    }
    for method, path in required:
        operation = schema["paths"][path][method]
        parameters = operation.get("parameters", [])
        assert any(p.get("name") == "X-Automation-Key" and p.get("in") == "header" for p in parameters)


def test_m34_api_rejects_missing_automation_key(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        assert client.get("/integrity/parser-paper-campaign/status").status_code in {401, 403, 503}
    finally:
        app.dependency_overrides.clear()
