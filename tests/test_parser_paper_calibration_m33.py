from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401
from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.models.blockchain_integrity import (
    CanonicalParserPaperCalibrationCampaign,
    CanonicalParserPaperCalibrationEvidence,
    CanonicalParserPaperExecutionPermit,
    CanonicalParserPermitBoundPaperExecution,
    CanonicalParserUnifiedDecisionResult,
    CanonicalParserUnifiedDecisionRun,
)
from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_order import PaperOrder
import backend.app.services.blockchain_parser_paper_calibration_service as service
from backend.app.main import app

NOW = datetime(2026, 7, 28, 20, 0, tzinfo=timezone.utc)


def calibration_settings(**overrides):
    values = {
        "CANONICAL_PARSER_PAPER_CALIBRATION_ENABLED": True,
        "CANONICAL_PARSER_PAPER_CALIBRATION_DEFAULT_LOOKBACK_DAYS": 30,
        "CANONICAL_PARSER_PAPER_CALIBRATION_MIN_SETTLED_ATTEMPTS": 4,
        "CANONICAL_PARSER_PAPER_CALIBRATION_MIN_CLOSED_OUTCOMES": 2,
        "CANONICAL_PARSER_PAPER_CALIBRATION_MAX_CALIBRATION_GAP_PERCENT": 20.0,
        "CANONICAL_PARSER_PAPER_CALIBRATION_MIN_RELIABILITY_SCORE": 98.0,
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


def seed_base(db: Session):
    account = PaperAccount(
        name=f"cal-{id(db)}",
        status="ACTIVE",
        starting_balance_sol=10.0,
        cash_balance_sol=10.0,
        realized_pnl_sol=0.0,
        max_position_size_sol=1.0,
        max_open_positions=10,
        daily_loss_limit_sol=5.0,
    )
    db.add(account)
    db.flush()
    run = CanonicalParserUnifiedDecisionRun(
        run_id="70000000-0000-0000-0000-000000000001",
        run_key="7" * 64,
        scope="SHADOW_DECISION_ONLY",
        status="COMPLETED",
        source_trade_count=1,
        source_token_count=1,
        source_wallet_count=2,
        qualified_wallet_count=2,
        result_count=1,
        approve_count=1,
        review_count=0,
        reject_count=0,
        insufficient_data_count=0,
        policy_version="m31-test",
        policy_hash="8" * 64,
        policy_snapshot={},
        parameters={},
        summary={},
        safety={},
        evidence_hash="9" * 64,
        actor_label="TEST",
        note=None,
        data_start_at=NOW,
        data_end_at=NOW,
        started_at=NOW,
        completed_at=NOW,
        valid_until=NOW + timedelta(hours=1),
        technical_metadata={},
    )
    db.add(run)
    db.flush()
    decision = CanonicalParserUnifiedDecisionResult(
        result_id="71000000-0000-0000-0000-000000000001",
        run_db_id=run.id,
        sequence=1,
        decision="APPROVE",
        token_mint="CalibrationToken11111111111111111111111111111111",
        source_trade_ids=[1],
        source_signatures=["sig"],
        source_event_at=NOW,
        raw_wallet_count=2,
        qualified_wallet_count=2,
        independent_cluster_count=2,
        follower_wallet_count=0,
        leader_wallet="Wallet1111111111111111111111111111111111111",
        signal_score=82,
        confidence_score=80,
        uncertainty_score=20,
        requested_size_sol=0.1,
        approved_size_sol=0.1,
        token_safety_status="SAFE",
        timing_status="COPYABLE",
        market_regime="UNKNOWN",
        confidence_calibration_status="BASELINE_HEURISTIC_UNCALIBRATED",
        reason_codes=[],
        positive_factors=[],
        evidence_snapshot={},
        exit_plan={},
        counterfactuals=[],
        decision_hash="a" * 64,
    )
    db.add(decision)
    db.flush()
    permit = CanonicalParserPaperExecutionPermit(
        permit_id="72000000-0000-0000-0000-000000000001",
        permit_key="b" * 64,
        readiness_assessment_db_id=1,
        readiness_assessment_id="73000000-0000-0000-0000-000000000001",
        readiness_evidence_hash="c" * 64,
        binding_db_id=1,
        binding_id="74000000-0000-0000-0000-000000000001",
        binding_event_hash="d" * 64,
        certification_id="75000000-0000-0000-0000-000000000001",
        paper_account_id=account.id,
        paper_account_name=account.name,
        scope="PAPER_EXECUTION_METADATA_ONLY",
        status="ACTIVE",
        requested_validity_minutes=60,
        total_budget_sol=10,
        max_order_budget_sol=1,
        max_order_count=100,
        consumed_budget_sol=0,
        consumed_order_count=0,
        policy_version="m30-test",
        policy_hash="e" * 64,
        policy_snapshot={},
        actor_label="TEST",
        note=None,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash="f" * 64,
        technical_metadata={},
    )
    db.add(permit)
    db.commit()
    return account, decision, permit


def add_attempt(
    db: Session,
    account: PaperAccount,
    decision: CanonicalParserUnifiedDecisionResult,
    permit: CanonicalParserPaperExecutionPermit,
    *,
    sequence: int,
    side: str,
    status: str = "SETTLED",
    pnl: float = 0.0,
    fee: float = 0.001,
    confidence: float = 80.0,
    signal: float = 82.0,
    reserved_budget: float | None = None,
    reserved_at: datetime = NOW,
    token: str | None = None,
):
    token_mint = token or decision.token_mint
    order = None
    if status == "SETTLED":
        order = PaperOrder(
            account_id=account.id,
            position_id=None,
            token_mint=token_mint,
            side=side,
            status="FILLED",
            requested_value_sol=0.1,
            quantity=100.0,
            execution_price_sol=0.00101 if side == "BUY" else 0.00119,
            gross_value_sol=0.1,
            fee_sol=fee,
            slippage_percent=1.0,
            realized_pnl_sol=pnl,
            signal_score=signal,
            reason=f"[M32:execution-{sequence}]",
            executed_at=reserved_at + timedelta(seconds=1),
            created_at=reserved_at,
        )
        db.add(order)
        db.flush()
    budget = (0.1 if side == "BUY" else 0.0) if reserved_budget is None else reserved_budget
    row = CanonicalParserPermitBoundPaperExecution(
        execution_id=f"76000000-0000-0000-0000-{sequence:012d}",
        idempotency_key=(f"{sequence:x}" * 64)[:64],
        permit_db_id=permit.id,
        permit_id=permit.permit_id,
        decision_result_db_id=decision.id,
        decision_result_id=decision.result_id,
        decision_hash=decision.decision_hash,
        paper_account_id=account.id,
        paper_order_id=None if order is None else order.id,
        paper_position_id=None,
        side=side,
        status=status,
        token_mint=token_mint,
        requested_budget_sol=budget,
        reserved_budget_sol=budget,
        settled_budget_sol=budget if status == "SETTLED" and side == "BUY" else 0,
        quantity=100,
        market_price_sol=0.001 if side == "BUY" else 0.0012,
        slippage_percent=1,
        fee_percent=0.25,
        signal_score=signal,
        confidence_score=confidence,
        permit_budget_before_sol=0,
        permit_order_count_before=max(0, sequence - 1),
        reservation_hash=("1" * 63) + str(sequence % 10),
        settlement_hash=None if status != "SETTLED" else (("2" * 63) + str(sequence % 10)),
        failure_code=None,
        failure_message=None,
        actor_label="TEST",
        note=None,
        reserved_at=reserved_at,
        settled_at=reserved_at + timedelta(seconds=2) if status == "SETTLED" else None,
        released_at=reserved_at + timedelta(seconds=2) if status in {"RELEASED", "FAILED"} else None,
        technical_metadata={},
        created_at=reserved_at,
    )
    db.add(row)
    db.flush()
    return row


def synchronize_permit(db: Session, permit: CanonicalParserPaperExecutionPermit):
    attempts = list(
        db.scalars(
            select(CanonicalParserPermitBoundPaperExecution).where(
                CanonicalParserPermitBoundPaperExecution.permit_id == permit.permit_id
            )
        )
    )
    active = [row for row in attempts if row.status in {"RESERVED", "RECONCILIATION_REQUIRED", "SETTLED"}]
    permit.consumed_budget_sol = sum(float(row.reserved_budget_sol) for row in active)
    permit.consumed_order_count = len(active)
    db.commit()


def seed_ready_campaign_data(db: Session, *, losing: bool = False, confidence: float = 90.0):
    account, decision, permit = seed_base(db)
    add_attempt(db, account, decision, permit, sequence=1, side="BUY", confidence=confidence)
    add_attempt(db, account, decision, permit, sequence=2, side="SELL", pnl=-0.02 if losing else 0.02, confidence=confidence)
    add_attempt(db, account, decision, permit, sequence=3, side="BUY", confidence=confidence, token="OtherToken1111111111111111111111111111111111")
    add_attempt(db, account, decision, permit, sequence=4, side="SELL", pnl=-0.01 if losing else 0.01, confidence=confidence, token="OtherToken1111111111111111111111111111111111")
    synchronize_permit(db, permit)
    return account, decision, permit


def preview(db, account, permit=None, settings_object=None):
    return service.preview_paper_calibration_campaign(
        db,
        paper_account_id=account.id,
        permit_id=None if permit is None else permit.permit_id,
        window_started_at=NOW - timedelta(minutes=5),
        window_ended_at=NOW + timedelta(minutes=5),
        settings_object=settings_object or calibration_settings(),
        evaluated_at=NOW + timedelta(minutes=5),
    )


def test_m33_flag_false_by_default():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        SOLANA_RPC_URL="https://api.mainnet-beta.solana.com",
        HELIUS_API_KEY="test",
    )
    assert configured.CANONICAL_PARSER_PAPER_CALIBRATION_ENABLED is False


def test_m33_models_registered():
    assert "canonical_parser_paper_calibration_campaigns" in Base.metadata.tables
    assert "canonical_parser_paper_calibration_evidence" in Base.metadata.tables


def test_m33_migration_is_consecutive_and_head():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("b8e5d0f3a742")
    assert revision.down_revision == "a7d4c9e2f631"
    assert scripts.get_heads() == ["b8e5d0f3a742"]


def test_status_is_analytics_only(db):
    payload = service.get_paper_calibration_status(db, settings_object=calibration_settings())
    assert payload["operational_guards"]["analytics_only"] is True
    assert payload["operational_guards"]["automatic_policy_changes"] is False
    assert payload["operational_guards"]["live_execution_authorized"] is False


def test_preview_without_attempts_is_insufficient(db):
    account, _, permit = seed_base(db)
    payload = preview(db, account, permit)
    assert payload["status"] == "INSUFFICIENT_DATA"
    assert "SETTLED_SAMPLE_INSUFFICIENT" in payload["reason_codes"]


def test_run_rejects_when_disabled(db):
    account, _, permit = seed_base(db)
    payload = preview(db, account, permit)
    with pytest.raises(service.CanonicalParserPaperCalibrationError) as raised:
        service.run_paper_calibration_campaign(
            db,
            paper_account_id=account.id,
            permit_id=permit.permit_id,
            window_started_at=payload["window_started_at"],
            window_ended_at=payload["window_ended_at"],
            confirmation=payload["confirmation"],
            settings_object=calibration_settings(CANONICAL_PARSER_PAPER_CALIBRATION_ENABLED=False),
            evaluated_at=NOW + timedelta(minutes=5),
        )
    assert raised.value.code == "PAPER_CALIBRATION_DISABLED"


def test_ready_campaign_computes_profitability_and_calibration(db):
    account, _, permit = seed_ready_campaign_data(db)
    payload = preview(db, account, permit)
    assert payload["status"] == "READY"
    assert payload["summary"]["closed_outcome_count"] == 2
    assert payload["summary"]["win_rate_percent"] == "100.0000"
    assert payload["summary"]["realized_pnl_sol"] == "0.030000000"
    assert payload["summary"]["brier_score"] is not None
    assert payload["summary"]["calibration_gap_percent"] == "10.0000"


def test_run_persists_campaign_and_evidence(db):
    account, _, permit = seed_ready_campaign_data(db)
    payload = preview(db, account, permit)
    campaign = service.run_paper_calibration_campaign(
        db,
        paper_account_id=account.id,
        permit_id=permit.permit_id,
        window_started_at=payload["window_started_at"],
        window_ended_at=payload["window_ended_at"],
        confirmation=payload["confirmation"],
        settings_object=calibration_settings(),
        evaluated_at=NOW + timedelta(minutes=5),
    )
    assert campaign["status"] == "READY"
    assert db.scalar(select(func.count(CanonicalParserPaperCalibrationCampaign.id))) == 1
    assert db.scalar(select(func.count(CanonicalParserPaperCalibrationEvidence.id))) == 4


def test_campaign_is_idempotent_for_same_window_and_evidence(db):
    account, _, permit = seed_ready_campaign_data(db)
    payload = preview(db, account, permit)
    kwargs = dict(
        paper_account_id=account.id,
        permit_id=permit.permit_id,
        window_started_at=payload["window_started_at"],
        window_ended_at=payload["window_ended_at"],
        confirmation=payload["confirmation"],
        settings_object=calibration_settings(),
        evaluated_at=NOW + timedelta(minutes=5),
    )
    first = service.run_paper_calibration_campaign(db, **kwargs)
    second = service.run_paper_calibration_campaign(db, **kwargs)
    assert second["campaign_id"] == first["campaign_id"]
    assert db.scalar(select(func.count(CanonicalParserPaperCalibrationCampaign.id))) == 1


def test_negative_pnl_causes_review(db):
    account, _, permit = seed_ready_campaign_data(db, losing=True, confidence=10)
    payload = preview(db, account, permit)
    assert payload["status"] == "REVIEW"
    assert "REALIZED_PNL_NEGATIVE" in payload["reason_codes"]


def test_high_confidence_losing_outcomes_show_calibration_gap(db):
    account, _, permit = seed_ready_campaign_data(db, losing=True, confidence=90)
    payload = preview(db, account, permit)
    assert payload["status"] == "REVIEW"
    assert payload["summary"]["calibration_gap_percent"] == "90.0000"
    assert "CONFIDENCE_CALIBRATION_GAP_HIGH" in payload["reason_codes"]


def test_budget_drift_blocks_campaign(db):
    account, _, permit = seed_ready_campaign_data(db)
    permit.consumed_budget_sol = 9
    db.commit()
    payload = preview(db, account, permit)
    assert payload["status"] == "BLOCKED"
    assert "PERMIT_BUDGET_DRIFT_DETECTED" in payload["reason_codes"]


def test_orphan_reservation_blocks_campaign(db):
    account, decision, permit = seed_base(db)
    orphan = add_attempt(
        db,
        account,
        decision,
        permit,
        sequence=1,
        side="BUY",
        status="RESERVED",
        reserved_at=NOW - timedelta(minutes=30),
    )
    # La reservation è vecchia, ma è stata osservata nella finestra di campagna.
    orphan.created_at = NOW
    synchronize_permit(db, permit)
    payload = preview(db, account, permit, settings_object=calibration_settings(
        CANONICAL_PARSER_PAPER_CALIBRATION_MIN_SETTLED_ATTEMPTS=1,
        CANONICAL_PARSER_PAPER_CALIBRATION_MIN_CLOSED_OUTCOMES=1,
    ))
    assert payload["status"] == "BLOCKED"
    assert "ORPHAN_RESERVATIONS_DETECTED" in payload["reason_codes"]


def test_segments_are_built_by_confidence_score_token_and_permit(db):
    account, _, permit = seed_ready_campaign_data(db)
    payload = preview(db, account, permit)
    segments = payload["segments"]
    assert "90-100" in segments["by_confidence_bucket"]
    assert "80-89" in segments["by_signal_score_bucket"]
    assert permit.permit_id in segments["by_permit"]
    assert len(segments["by_token"]) == 2


def test_get_campaign_returns_evidence(db):
    account, _, permit = seed_ready_campaign_data(db)
    payload = preview(db, account, permit)
    campaign = service.run_paper_calibration_campaign(
        db,
        paper_account_id=account.id,
        permit_id=permit.permit_id,
        window_started_at=payload["window_started_at"],
        window_ended_at=payload["window_ended_at"],
        confirmation=payload["confirmation"],
        settings_object=calibration_settings(),
        evaluated_at=NOW + timedelta(minutes=5),
    )
    detail = service.get_paper_calibration_campaign(db, campaign["campaign_id"])
    assert len(detail["evidence"]) == 4
    assert all(len(row["evidence_hash"]) == 64 for row in detail["evidence"])


def test_resolve_returns_latest_campaign(db):
    account, _, permit = seed_ready_campaign_data(db)
    payload = preview(db, account, permit)
    campaign = service.run_paper_calibration_campaign(
        db,
        paper_account_id=account.id,
        permit_id=permit.permit_id,
        window_started_at=payload["window_started_at"],
        window_ended_at=payload["window_ended_at"],
        confirmation=payload["confirmation"],
        settings_object=calibration_settings(),
        evaluated_at=NOW + timedelta(minutes=5),
    )
    resolved = service.resolve_paper_calibration_campaign(db, paper_account_id=account.id)
    assert resolved["resolved_status"] == "READY"
    assert resolved["latest_campaign"]["campaign_id"] == campaign["campaign_id"]


def test_invalid_account_and_window_are_rejected(db):
    with pytest.raises(service.CanonicalParserPaperCalibrationError) as missing:
        service.preview_paper_calibration_campaign(db, paper_account_id=999, settings_object=calibration_settings())
    assert missing.value.code == "PAPER_CALIBRATION_ACCOUNT_NOT_FOUND"
    account, _, _ = seed_base(db)
    with pytest.raises(service.CanonicalParserPaperCalibrationError) as invalid:
        service.preview_paper_calibration_campaign(
            db,
            paper_account_id=account.id,
            window_started_at=NOW,
            window_ended_at=NOW,
            settings_object=calibration_settings(),
        )
    assert invalid.value.code == "PAPER_CALIBRATION_INVALID_WINDOW"


def test_campaign_does_not_mutate_operational_records(db):
    account, _, permit = seed_ready_campaign_data(db)
    account_before = (account.cash_balance_sol, account.realized_pnl_sol)
    permit_before = (float(permit.consumed_budget_sol), permit.consumed_order_count)
    order_count_before = db.scalar(select(func.count(PaperOrder.id)))
    payload = preview(db, account, permit)
    service.run_paper_calibration_campaign(
        db,
        paper_account_id=account.id,
        permit_id=permit.permit_id,
        window_started_at=payload["window_started_at"],
        window_ended_at=payload["window_ended_at"],
        confirmation=payload["confirmation"],
        settings_object=calibration_settings(),
        evaluated_at=NOW + timedelta(minutes=5),
    )
    db.refresh(account)
    db.refresh(permit)
    assert (account.cash_balance_sol, account.realized_pnl_sol) == account_before
    assert (float(permit.consumed_budget_sol), permit.consumed_order_count) == permit_before
    assert db.scalar(select(func.count(PaperOrder.id))) == order_count_before


def test_m33_openapi_operations_have_automation_header():
    schema = app.openapi()
    expected = {
        ("get", "/integrity/parser-paper-calibration/status"),
        ("get", "/integrity/parser-paper-calibration/preview"),
        ("post", "/integrity/parser-paper-calibration/run"),
        ("get", "/integrity/parser-paper-calibration/campaigns/{campaign_id}"),
        ("get", "/integrity/parser-paper-calibration/resolve"),
    }
    for method, path in expected:
        operation = schema["paths"][path][method]
        headers = {p["name"].lower() for p in operation.get("parameters", []) if p.get("in") == "header"}
        assert "x-automation-key" in headers


def test_m33_service_has_no_operational_write_targets_or_external_calls():
    path = Path("backend/app/services/blockchain_parser_paper_calibration_service.py")
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
    assert "PaperOrder(" not in source
    assert "PaperPosition(" not in source
    assert "Trade(" not in source
    assert "automatic_policy_changes\": True" not in source
