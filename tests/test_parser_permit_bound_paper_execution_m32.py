from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401
from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.main import app
from backend.app.models.blockchain_integrity import (
    CanonicalParserPaperExecutionPermit,
    CanonicalParserPermitBoundPaperExecution,
    CanonicalParserPermitBoundPaperExecutionEvent,
    CanonicalParserUnifiedDecisionResult,
    CanonicalParserUnifiedDecisionRun,
)
from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_order import PaperOrder
from backend.app.models.paper_position import PaperPosition
import backend.app.services.blockchain_parser_permit_bound_paper_execution_service as service

NOW = datetime(2026, 7, 28, 20, 0, tzinfo=timezone.utc)


def enabled_settings(**overrides):
    values = {
        "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_ENABLED": True,
        "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_RESERVATION_TIMEOUT_MINUTES": 10,
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


def seed_context(
    db: Session,
    *,
    decision: str = "APPROVE",
    token_status: str = "SAFE",
    timing_status: str = "COPYABLE",
    run_completed_at: datetime = NOW,
    run_valid_until: datetime | None = None,
    approved_size: float = 0.1,
    account_status: str = "ACTIVE",
    cash: float = 10.0,
    consumed_budget: float = 0.0,
    consumed_orders: int = 0,
    total_budget: float = 1.0,
    max_order_budget: float = 0.2,
    max_order_count: int = 10,
):
    account = PaperAccount(
        name=f"paper-{id(db)}-{db.query(PaperAccount).count()}",
        status=account_status,
        starting_balance_sol=10.0,
        cash_balance_sol=cash,
        realized_pnl_sol=0.0,
        max_position_size_sol=1.0,
        max_open_positions=5,
        daily_loss_limit_sol=5.0,
    )
    db.add(account)
    db.flush()
    run = CanonicalParserUnifiedDecisionRun(
        run_id=f"00000000-0000-0000-0000-{db.query(CanonicalParserUnifiedDecisionRun).count()+1:012d}",
        run_key=("a" * 63) + str(db.query(CanonicalParserUnifiedDecisionRun).count() % 10),
        scope="SHADOW_DECISION_ONLY",
        status="COMPLETED",
        source_trade_count=1,
        source_token_count=1,
        source_wallet_count=2,
        qualified_wallet_count=2,
        result_count=1,
        approve_count=1 if decision == "APPROVE" else 0,
        review_count=1 if decision == "REVIEW" else 0,
        reject_count=1 if decision == "REJECT" else 0,
        insufficient_data_count=1 if decision == "INSUFFICIENT_DATA" else 0,
        policy_version="m31-test",
        policy_hash="b" * 64,
        policy_snapshot={},
        parameters={},
        summary={},
        safety={},
        evidence_hash="c" * 64,
        actor_label="TEST",
        note=None,
        data_start_at=run_completed_at,
        data_end_at=run_completed_at,
        started_at=run_completed_at,
        completed_at=run_completed_at,
        valid_until=run_valid_until or (run_completed_at + timedelta(hours=1)),
        technical_metadata={},
    )
    db.add(run)
    db.flush()
    result = CanonicalParserUnifiedDecisionResult(
        result_id=f"10000000-0000-0000-0000-{db.query(CanonicalParserUnifiedDecisionResult).count()+1:012d}",
        run_db_id=run.id,
        sequence=1,
        decision=decision,
        token_mint="TokenMint111111111111111111111111111111111111",
        source_trade_ids=[1],
        source_signatures=["sig"],
        source_event_at=run_completed_at,
        raw_wallet_count=2,
        qualified_wallet_count=2,
        independent_cluster_count=2,
        follower_wallet_count=0,
        leader_wallet="Wallet1111111111111111111111111111111111111",
        signal_score=82,
        confidence_score=80,
        uncertainty_score=20,
        requested_size_sol=max(approved_size, 0),
        approved_size_sol=max(approved_size, 0),
        token_safety_status=token_status,
        timing_status=timing_status,
        market_regime="UNKNOWN",
        confidence_calibration_status="BASELINE_HEURISTIC_UNCALIBRATED",
        reason_codes=[],
        positive_factors=[],
        evidence_snapshot={},
        exit_plan={"status": "PLANNED", "normal_exit": "SOURCE_SELL"},
        counterfactuals=[],
        decision_hash="d" * 64,
    )
    result.decision_hash = service._calculate_decision_hash(result)
    db.add(result)
    db.flush()
    permit = CanonicalParserPaperExecutionPermit(
        permit_id=f"20000000-0000-0000-0000-{db.query(CanonicalParserPaperExecutionPermit).count()+1:012d}",
        permit_key=("e" * 63) + str(db.query(CanonicalParserPaperExecutionPermit).count() % 10),
        readiness_assessment_db_id=1,
        readiness_assessment_id="30000000-0000-0000-0000-000000000001",
        readiness_evidence_hash="f" * 64,
        binding_db_id=1,
        binding_id="40000000-0000-0000-0000-000000000001",
        binding_event_hash="1" * 64,
        certification_id="50000000-0000-0000-0000-000000000001",
        paper_account_id=account.id,
        paper_account_name=account.name,
        scope="PAPER_EXECUTION_METADATA_ONLY",
        status="ACTIVE",
        requested_validity_minutes=60,
        total_budget_sol=total_budget,
        max_order_budget_sol=max_order_budget,
        max_order_count=max_order_count,
        consumed_budget_sol=consumed_budget,
        consumed_order_count=consumed_orders,
        policy_version="m30-test",
        policy_hash="2" * 64,
        policy_snapshot={},
        actor_label="TEST",
        note=None,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash="3" * 64,
        technical_metadata={},
    )
    db.add(permit)
    db.commit()
    return account, run, result, permit


def active_permit(monkeypatch, permit):
    monkeypatch.setattr(
        service,
        "resolve_paper_execution_permit",
        lambda *args, **kwargs: {"permit_id": permit.permit_id, "resolved_status": "ACTIVE"},
    )


def preview(db, permit, result, **kwargs):
    return service.preview_permit_bound_paper_execution(
        db,
        permit_id=permit.permit_id,
        decision_result_id=result.result_id,
        side=kwargs.pop("side", "BUY"),
        market_price_sol=kwargs.pop("market_price_sol", 0.001),
        idempotency_token=kwargs.pop("idempotency_token", "token-12345678"),
        settings_object=kwargs.pop("settings_object", enabled_settings()),
        evaluated_at=kwargs.pop("evaluated_at", NOW + timedelta(minutes=1)),
        **kwargs,
    )


def test_m32_flags_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_ENABLED is False


def test_m32_models_are_registered():
    assert "canonical_parser_permit_bound_paper_executions" in Base.metadata.tables
    assert "canonical_parser_permit_bound_paper_execution_events" in Base.metadata.tables


def test_m32_migration_is_consecutive():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("a7d4c9e2f631")
    assert revision.down_revision == "f2c8a6d1e735"


def test_status_is_manual_and_live_closed(db):
    status = service.get_permit_bound_paper_execution_status(db, settings_object=enabled_settings())
    assert status["operational_guards"]["manual_only"] is True
    assert status["operational_guards"]["trade_writes"] is False
    assert status["operational_guards"]["live_execution_authorized"] is False


def test_preview_caps_budget_by_decision_and_permit(db, monkeypatch):
    _, _, result, permit = seed_context(db, approved_size=0.5, max_order_budget=0.2, total_budget=0.25, consumed_budget=0.1)
    active_permit(monkeypatch, permit)
    payload = preview(db, permit, result)
    assert payload["reserved_budget_sol"] == "0.150000000"
    assert payload["confirmation"].startswith("EXECUTE_PERMIT_BOUND_PAPER:")


def test_execute_rejects_when_flag_disabled(db, monkeypatch):
    _, _, result, permit = seed_context(db)
    active_permit(monkeypatch, permit)
    payload = preview(db, permit, result)
    with pytest.raises(service.CanonicalParserPermitBoundPaperExecutionError) as raised:
        service.execute_permit_bound_paper(
            db,
            permit_id=permit.permit_id,
            decision_result_id=result.result_id,
            side="BUY",
            market_price_sol=0.001,
            idempotency_token="token-12345678",
            confirmation=payload["confirmation"],
            settings_object=enabled_settings(CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_ENABLED=False),
            executed_at=NOW + timedelta(minutes=1),
        )
    assert raised.value.code == "PAPER_EXECUTION_DISABLED"


def test_execute_requires_exact_confirmation(db, monkeypatch):
    _, _, result, permit = seed_context(db)
    active_permit(monkeypatch, permit)
    with pytest.raises(service.CanonicalParserPermitBoundPaperExecutionError) as raised:
        service.execute_permit_bound_paper(
            db,
            permit_id=permit.permit_id,
            decision_result_id=result.result_id,
            side="BUY",
            market_price_sol=0.001,
            idempotency_token="token-12345678",
            confirmation="WRONG",
            settings_object=enabled_settings(),
            executed_at=NOW + timedelta(minutes=1),
        )
    assert raised.value.code == "PAPER_EXECUTION_CONFIRMATION_REQUIRED"


@pytest.mark.parametrize(
    ("decision", "token_status", "timing_status", "expected"),
    [
        ("REVIEW", "SAFE", "COPYABLE", "PAPER_EXECUTION_DECISION_NOT_APPROVED"),
        ("APPROVE", "UNSAFE", "COPYABLE", "PAPER_EXECUTION_DECISION_GUARDS_FAILED"),
        ("APPROVE", "SAFE", "LATE", "PAPER_EXECUTION_DECISION_GUARDS_FAILED"),
    ],
)
def test_preview_rejects_non_executable_decisions(db, monkeypatch, decision, token_status, timing_status, expected):
    _, _, result, permit = seed_context(db, decision=decision, token_status=token_status, timing_status=timing_status)
    active_permit(monkeypatch, permit)
    with pytest.raises(service.CanonicalParserPermitBoundPaperExecutionError) as raised:
        preview(db, permit, result)
    assert raised.value.code == expected


def test_preview_rejects_expired_decision(db, monkeypatch):
    _, _, result, permit = seed_context(
        db,
        run_completed_at=NOW - timedelta(hours=2),
        run_valid_until=NOW - timedelta(hours=1),
    )
    active_permit(monkeypatch, permit)
    with pytest.raises(service.CanonicalParserPermitBoundPaperExecutionError) as raised:
        preview(db, permit, result)
    assert raised.value.code == "PAPER_EXECUTION_DECISION_EXPIRED"


def test_preview_rejects_tampered_decision_hash(db, monkeypatch):
    _, _, result, permit = seed_context(db)
    active_permit(monkeypatch, permit)
    result.signal_score = 99
    db.commit()
    with pytest.raises(service.CanonicalParserPermitBoundPaperExecutionError) as exc:
        preview(db, permit, result)
    assert exc.value.code == "PAPER_EXECUTION_DECISION_HASH_INVALID"


def test_preview_requires_exit_plan(db, monkeypatch):
    _, _, result, permit = seed_context(db)
    active_permit(monkeypatch, permit)
    result.exit_plan = {}
    result.decision_hash = service._calculate_decision_hash(result)
    db.commit()
    with pytest.raises(service.CanonicalParserPermitBoundPaperExecutionError) as exc:
        preview(db, permit, result)
    assert exc.value.code == "PAPER_EXECUTION_EXIT_PLAN_REQUIRED"


def test_preview_rejects_exhausted_budget(db, monkeypatch):
    _, _, result, permit = seed_context(
        db, total_budget=0.1, max_order_budget=0.1, consumed_budget=0.1
    )
    active_permit(monkeypatch, permit)
    with pytest.raises(service.CanonicalParserPermitBoundPaperExecutionError) as raised:
        preview(db, permit, result)
    assert raised.value.code == "PAPER_EXECUTION_BUDGET_EXHAUSTED"


def test_preview_rejects_exhausted_order_count(db, monkeypatch):
    _, _, result, permit = seed_context(db, max_order_count=1, consumed_orders=1)
    active_permit(monkeypatch, permit)
    with pytest.raises(service.CanonicalParserPermitBoundPaperExecutionError) as raised:
        preview(db, permit, result)
    assert raised.value.code == "PAPER_EXECUTION_ORDER_LIMIT"


def test_buy_execution_settles_and_updates_permit(db, monkeypatch):
    account, _, result, permit = seed_context(db)
    active_permit(monkeypatch, permit)
    payload = preview(db, permit, result)
    executed = service.execute_permit_bound_paper(
        db,
        permit_id=permit.permit_id,
        decision_result_id=result.result_id,
        side="BUY",
        market_price_sol=0.001,
        idempotency_token="token-12345678",
        confirmation=payload["confirmation"],
        settings_object=enabled_settings(),
        executed_at=NOW + timedelta(minutes=1),
    )
    assert executed["status"] == "SETTLED"
    assert executed["paper_order_id"] is not None
    assert db.scalar(select(func.count(PaperOrder.id))) == 1
    assert db.scalar(select(func.count(PaperPosition.id))) == 1
    refreshed = db.get(CanonicalParserPaperExecutionPermit, permit.id)
    assert float(refreshed.consumed_budget_sol) == pytest.approx(0.1)
    assert refreshed.consumed_order_count == 1
    assert db.get(PaperAccount, account.id).cash_balance_sol < 10


def test_execution_is_idempotent_without_duplicate_order(db, monkeypatch):
    _, _, result, permit = seed_context(db)
    active_permit(monkeypatch, permit)
    payload = preview(db, permit, result)
    kwargs = dict(
        permit_id=permit.permit_id,
        decision_result_id=result.result_id,
        side="BUY",
        market_price_sol=0.001,
        idempotency_token="token-12345678",
        confirmation=payload["confirmation"],
        settings_object=enabled_settings(),
        executed_at=NOW + timedelta(minutes=1),
    )
    first = service.execute_permit_bound_paper(db, **kwargs)
    monkeypatch.setattr(service, "resolve_paper_execution_permit", lambda *a, **k: {"resolved_status": "EXPIRED"})
    second = service.execute_permit_bound_paper(db, **kwargs)
    assert second["execution_id"] == first["execution_id"]
    assert db.scalar(select(func.count(PaperOrder.id))) == 1
    assert db.scalar(select(func.count(CanonicalParserPermitBoundPaperExecution.id))) == 1


def test_failed_paper_engine_releases_reservation(db, monkeypatch):
    _, _, result, permit = seed_context(db, account_status="PAUSED")
    active_permit(monkeypatch, permit)
    payload = preview(db, permit, result)
    with pytest.raises(service.CanonicalParserPermitBoundPaperExecutionError) as raised:
        service.execute_permit_bound_paper(
            db,
            permit_id=permit.permit_id,
            decision_result_id=result.result_id,
            side="BUY",
            market_price_sol=0.001,
            idempotency_token="token-12345678",
            confirmation=payload["confirmation"],
            settings_object=enabled_settings(),
            executed_at=NOW + timedelta(minutes=1),
        )
    assert raised.value.code == "PAPER_ENGINE_ACCOUNT_NOT_ACTIVE"
    attempt = db.scalar(select(CanonicalParserPermitBoundPaperExecution))
    assert attempt.status == "RELEASED"
    refreshed = db.get(CanonicalParserPaperExecutionPermit, permit.id)
    assert float(refreshed.consumed_budget_sol) == 0
    assert refreshed.consumed_order_count == 0


def test_sell_execution_uses_no_new_budget(db, monkeypatch):
    account, _, result, permit = seed_context(db)
    active_permit(monkeypatch, permit)
    buy_preview = preview(db, permit, result, idempotency_token="buy-token-12345")
    service.execute_permit_bound_paper(
        db,
        permit_id=permit.permit_id,
        decision_result_id=result.result_id,
        side="BUY",
        market_price_sol=0.001,
        idempotency_token="buy-token-12345",
        confirmation=buy_preview["confirmation"],
        settings_object=enabled_settings(),
        executed_at=NOW + timedelta(minutes=1),
    )
    budget_after_buy = float(db.get(CanonicalParserPaperExecutionPermit, permit.id).consumed_budget_sol)
    sell_preview = preview(
        db,
        permit,
        result,
        side="SELL",
        market_price_sol=0.0012,
        idempotency_token="sell-token-1234",
        evaluated_at=NOW + timedelta(minutes=2),
    )
    sold = service.execute_permit_bound_paper(
        db,
        permit_id=permit.permit_id,
        decision_result_id=result.result_id,
        side="SELL",
        market_price_sol=0.0012,
        idempotency_token="sell-token-1234",
        confirmation=sell_preview["confirmation"],
        quantity=float(sell_preview["quantity"]),
        settings_object=enabled_settings(),
        executed_at=NOW + timedelta(minutes=2),
    )
    refreshed = db.get(CanonicalParserPaperExecutionPermit, permit.id)
    assert sold["status"] == "SETTLED"
    assert float(refreshed.consumed_budget_sol) == pytest.approx(budget_after_buy)
    assert refreshed.consumed_order_count == 2
    assert db.scalar(select(PaperPosition).where(PaperPosition.account_id == account.id)).status == "CLOSED"


def test_sell_requires_open_position(db, monkeypatch):
    _, _, result, permit = seed_context(db)
    active_permit(monkeypatch, permit)
    with pytest.raises(service.CanonicalParserPermitBoundPaperExecutionError) as raised:
        preview(db, permit, result, side="SELL")
    assert raised.value.code == "PAPER_EXECUTION_POSITION_NOT_FOUND"


def test_reconcile_marks_pending_before_timeout(db, monkeypatch):
    _, _, result, permit = seed_context(db)
    active_permit(monkeypatch, permit)
    payload = preview(db, permit, result)
    # Reserve by forcing the paper engine to raise after creating no order.
    monkeypatch.setattr(service, "buy_paper_token", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        service.execute_permit_bound_paper(
            db,
            permit_id=permit.permit_id,
            decision_result_id=result.result_id,
            side="BUY",
            market_price_sol=0.001,
            idempotency_token="token-12345678",
            confirmation=payload["confirmation"],
            settings_object=enabled_settings(),
            executed_at=NOW + timedelta(minutes=1),
        )
    # Unexpected errors retain the reservation until explicit reconciliation.
    row = db.scalar(select(CanonicalParserPermitBoundPaperExecution))
    assert row.status == "RECONCILIATION_REQUIRED"
    assert float(permit.consumed_budget_sol) == pytest.approx(0.1)
    assert permit.consumed_order_count == 1


def test_reconcile_releases_expired_reservation(db):
    account, _, result, permit = seed_context(db, consumed_budget=0.1, consumed_orders=1)
    row = CanonicalParserPermitBoundPaperExecution(
        execution_id="60000000-0000-0000-0000-000000000001",
        idempotency_key="4" * 64,
        permit_db_id=permit.id,
        permit_id=permit.permit_id,
        decision_result_db_id=result.id,
        decision_result_id=result.result_id,
        decision_hash=result.decision_hash,
        paper_account_id=account.id,
        paper_order_id=None,
        paper_position_id=None,
        side="BUY",
        status="RESERVED",
        token_mint=result.token_mint,
        requested_budget_sol=0.1,
        reserved_budget_sol=0.1,
        settled_budget_sol=0,
        quantity=0,
        market_price_sol=0.001,
        slippage_percent=0.5,
        fee_percent=0.25,
        signal_score=82,
        confidence_score=80,
        permit_budget_before_sol=0,
        permit_order_count_before=0,
        reservation_hash="5" * 64,
        settlement_hash=None,
        failure_code=None,
        failure_message=None,
        actor_label="TEST",
        note=None,
        reserved_at=NOW - timedelta(minutes=20),
        settled_at=None,
        released_at=None,
        technical_metadata={},
    )
    db.add(row)
    db.flush()
    service._append_event(db, row, event_type="RESERVED", details={})
    db.commit()
    reconciled = service.reconcile_permit_bound_paper_execution(
        db,
        execution_id=row.execution_id,
        confirmation=f"RECONCILE_PERMIT_BOUND_PAPER:{row.execution_id}:{row.reservation_hash}",
        settings_object=enabled_settings(),
        evaluated_at=NOW,
    )
    assert reconciled["status"] == "RELEASED"
    refreshed = db.get(CanonicalParserPaperExecutionPermit, permit.id)
    assert float(refreshed.consumed_budget_sol) == 0
    assert refreshed.consumed_order_count == 0


def test_execution_audit_chain_is_valid(db, monkeypatch):
    _, _, result, permit = seed_context(db)
    active_permit(monkeypatch, permit)
    payload = preview(db, permit, result)
    executed = service.execute_permit_bound_paper(
        db,
        permit_id=permit.permit_id,
        decision_result_id=result.result_id,
        side="BUY",
        market_price_sol=0.001,
        idempotency_token="token-12345678",
        confirmation=payload["confirmation"],
        settings_object=enabled_settings(),
        executed_at=NOW + timedelta(minutes=1),
    )
    detail = service.get_permit_bound_paper_execution(db, executed["execution_id"])
    assert detail["audit_reason_codes"] == []
    assert [event["event_type"] for event in detail["events"]] == ["RESERVED", "SETTLED"]


def test_m32_openapi_operations_have_automation_header(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        schema = app.openapi()
    finally:
        app.dependency_overrides.clear()
        app.openapi_schema = None
    expected = {
        ("get", "/integrity/parser-permit-bound-paper-execution/status"),
        ("get", "/integrity/parser-permit-bound-paper-execution/preview"),
        ("post", "/integrity/parser-permit-bound-paper-execution/execute"),
        ("post", "/integrity/parser-permit-bound-paper-execution/reconcile"),
        ("get", "/integrity/parser-permit-bound-paper-execution/executions/{execution_id}"),
        ("get", "/integrity/parser-permit-bound-paper-execution/resolve"),
    }
    for method, path in expected:
        operation = schema["paths"][path][method]
        headers = {p["name"].lower() for p in operation.get("parameters", []) if p.get("in") == "header"}
        assert "x-automation-key" in headers


def test_m32_service_has_no_live_or_external_call_targets():
    path = Path("backend/app/services/blockchain_parser_permit_bound_paper_execution_service.py")
    tree = ast.parse(path.read_text())
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("live" in name.lower() for name in imports)
    assert not any(name in {"httpx", "requests", "aiohttp"} for name in imports)
    source = path.read_text()
    assert "Trade(" not in source
    assert "live_execution_authorized\": True" not in source
